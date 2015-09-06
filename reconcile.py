#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
from math import log, sqrt
import json
from collections import defaultdict, Counter, namedtuple

def jsonToList( f ):
	"""Reads one JSON entry per line from  f  and returns a list of the results"""
	results = []
	for line in f:
		results.append( json.loads( line ) )
	return results

def manufacturerNormalizer(listing_manufacturers, product_manufacturers):
	"""Returns a dictionary mapping listing manufacturers to product
	ones (if such a manufacturer exists)"""
	product_manufacturers = set(product_manufacturers)
	
	listing_manufacturers = set(listing_manufacturers)
	
	results = {}
	for product_manufacturer in product_manufacturers:
		# Processed will keep track of which listing manufacturers we've
		# handled this time around so that we can avoid checking them
		# again in the future.
		# We need to store them and remove them at the end to avoid
		# modifying the set as we iterate over it.
		processed = set()
		for listing_manufacturer in listing_manufacturers:
			if any( bit in listing_manufacturer.split() for bit in product_manufacturer.split() ):
				results[listing_manufacturer] = product_manufacturer
				processed.add( listing_manufacturer )
		listing_manufacturers -= processed

	return results

def ngrams( n, bits):
	"""Given a value n and a tokenized string, 
	generates all n-grams and normalizes them."""
	for i in xrange( len(bits) - n + 1):
		result = normalize(''.join(bits[i:i+n]))
		if not result.strip():
			continue
		yield result

def normalize(s):
	"""Normalize by stripping out all characters that might get 
	omitted from product names"""
	return s.replace(" ", '').replace('_','').replace('-','')

currencyRatios = json.load( open('exchangerates.json', 'rt') )

def getCost( listing ):
	"""Normalizes costs to USD. Exchange rates are approximations."""
	return float( listing['price'] ) * currencyRatios[listing['currency']]

# Because we're going to be using products as dict keys, they need to be immutable.
# A named tuple is a nice way to do that.
Product = namedtuple('Product', 'product_name manufacturer model family announced_date')

class Reconciler( object ):
	def __init__(self, listings, products, debug=False):
		self.debug = debug
		self.listings = listings
		self.products = [ Product( 
			p['product_name'], 
			p['manufacturer'], 
			p['model'], 
			p['family'] if 'family' in p else '', 
			p['announced-date']) for p in products]

		self.manufacturer_map = manufacturerNormalizer(
			(l['manufacturer'] for l in listings), 
			(p['manufacturer'] for p in products))

		self.list_word_score = self.buildListingFrequencies()
		self.words_by_manufacturer = self.buildProductFrequencies()
		
	def buildListingFrequencies(self):
		word_frequency = defaultdict(int)

		# Compute the amount of information (entropy) in each word found in listings.
		# This value will be used later to weight guesses
		for listing in self.listings:
			for n in xrange(1,3):
				for word in ngrams(n, listing['title'].split()):
					word_frequency[word] += 1
		num_listings = float(len(self.listings))
		return { word: -log( word_frequency[word] / num_listings )
			for word in word_frequency.keys() }

	def buildProductFrequencies(self):
		# Compute the amount of information in each model and family name.
		# Because we restrict matching by manufacturer, all scores are
		# per-manufacturer.
		products_by_manufacturer = defaultdict(list)
		for product in self.products:
			products_by_manufacturer[product.manufacturer].append(product)
		
		words_by_manufacturer = {}
		for manufacturer, products in products_by_manufacturer.items():
			word_map = defaultdict(list)
			for product in products:
				word_map[normalize(product.family)].append( product )
				word_map[normalize(product.model)].append( product )
			
			num_products = float(len(products))
			words_by_manufacturer[manufacturer] = (
				word_map, { word: -log( len(word_map[word]) / num_products )
				for word in word_map.keys() } )
		return words_by_manufacturer

	def isCamera(self, listing):
		"""Employs several heuristics to try to determine whether
		a listing refers to a digital camera, or some other type of
		product. Ideally, this would be (or include) a Bayesian classifier
		trained on human classified data.

		Instead, my priors are all derived via posterior extraction."""
		
		# As crude as they are, these heuristics seem to work well enough.
		p = 1
		
		cost = getCost( listing )
		if cost < 30:
			p = 0.1
		elif cost < 50:
			p = 0.3
		elif cost < 100:
			p = 0.5
		title = listing['title'].upper()
		if 'MP' in title or 'MEGAPIXEL' in title:
			p += 0.5
		if 'OPTICAL ZOOM' in title:
			p += 0.3
		# ...battery for <models> ...
		if ' FOR ' in title:
			p -= 0.2
		# ... digital camera with <features> ...
		if ' WITH ' in title:
			p += 0.2
		return p >= 0.5

	def findCandidateProducts( self, listing ):
		"""Ranks products based on how many characteristics they share
		with the listing.

		Returns a dictionary mapping product to score."""
		if not self.isCamera( listing ) or listing['manufacturer'] not in self.manufacturer_map:
			return {}
		manufacturer = self.manufacturer_map[ listing['manufacturer'] ]
		word_map, word_score = self.words_by_manufacturer[manufacturer]
		results = defaultdict( float )

		for n in xrange(1,3):

			for word in ngrams(n, listing['title'].split()):

				dampener = self.list_word_score.get(word, 1)
				if word in word_map:
					word_products = word_map[word]
					score_incr = word_score[word]

					for product in word_products:
						if product.manufacturer == manufacturer:
							results[product] += score_incr * dampener

		return results

	def reconcile(self, score_threshold=35):
		"""Reconciles listings with products."""
		match_results = defaultdict(list)
		for listing in self.listings:
			results = self.findCandidateProducts( listing )
			hits = sorted( results.items(), key=lambda (_,s): s )
			if hits:
				product, score = hits[-1]

				if score > score_threshold:
					if len( hits ) > 1:
						# If we have more than one prospect, and their
						# scores only differ by a little, we're too
						# uncertain.
						# (Looking at pruned results, in most cases,
						# the scores were the same.)
						_, other_score = hits[-2]
						if score - other_score < 2:
							continue
					match_results[product.product_name].append( listing)
					if self.debug:
						listing['score']  = score

		return match_results

	def pruneByCost(self, match_results, sanity_factor = 1.5, sd_threshold = 0.1 ):
		"""Makes the assumption that similar products will be somewhat similarly priced,
		and that great outliers are likely different products instead.

		Items will only be pruned if: 
		  * there are more than two listings
		  * there is a sufficient spread in prices ( sd >= mean * sd_threshold ), 
		  * the listing's cost is more than sanity_factor * sd less than the mean price. 

		Experimentally, high-priced outliers were rarely false positives.

		This trades false negatives for reduced false positives.

		Modifies the match_results dict in place."""

		# Improved heuristics would distinguish between full kits and body only
		# (Boîtier seulement, nur Gehäuse, etc.) where applicable.
		for product, listings in match_results.items():
			if len( listings ) < 3:
				continue
			costs = map( getCost, listings )
			mean = sum(costs) / len(costs)
			sd = sqrt( sum( (cost - mean)**2 for cost in costs ) / (len(costs)-1) )
			if sd < mean * sd_threshold:
				continue
			listings = [listing for (listing, cost) in zip(listings, costs) if mean - cost < sd * sanity_factor]
			match_results[product] = listings
		return match_results

if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument('--score-threshold', type=int, default=35,
		help="Score threshold for a product to be considered a match to a listing. Default: 35")
	parser.add_argument("--sd-threshold", type=float, default=0.1, 
		help="Minimum ratio of standard deviation to mean to cull suspiciously inexpensive matches. Default: 0.1")
	parser.add_argument("--sanity-factor", type=float, default=1.5, 
		help="Matches more than this number times the standard deviation will be removed. Default: 1.5")
	parser.add_argument("--debug", action="store_true", help="Enable additional debugging output")
	parser.add_argument("--listings", type=argparse.FileType('rt'), default='listings.txt',
		help="JSON file containing listings. Default: listings.txt")
	parser.add_argument("--products", type=argparse.FileType('rt'), default='products.txt',
		help="JSON file containing products. Default: products.txt")
	parser.add_argument("--output", type=argparse.FileType('wt'), default='-',
		help="File to write reconciled output to. Default: stdout")
	parser.add_argument("--pretty-print", action="store_true", 
		help="Pretty-print output")
	args = parser.parse_args()
	listings = jsonToList(args.listings)
	products = jsonToList(args.products)

	reconciler = Reconciler( listings, products, debug=args.debug )
	match_results = reconciler.reconcile(args.score_threshold)
	reconciler.pruneByCost( match_results, args.sanity_factor, args.sd_threshold)
	json.dump( match_results, args.output, sort_keys=True, indent=4 if args.pretty_print else None )
	args.output.write("\n")
