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

def getCost( listing ):
	"""Normalizes costs to USD. Exchange rates are approximations."""
	currencyRatios = { 'USD': 1, 'CAD': 0.75, 'EUR': 1.1, 'GBP': 1.5 }
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

		self.manufacturerMap = manufacturerNormalizer(
			(l['manufacturer'] for l in listings), 
			(p['manufacturer'] for p in products))

		wordFrequency = defaultdict(int)

		# Compute the amount of information (entropy) in each word found in listings.
		# This value will be used later to weight guesses
		for listing in listings:
			for n in xrange(1,3):
				for word in ngrams(n, listing['title'].split()):
					wordFrequency[word] += 1
		numListings = float(len(listings))
		self.listWordScore = dict( 
			(word, -log( wordFrequency[word] / numListings )) 
			for word in wordFrequency.keys() )

		# Compute the amount of information in each model and family name.
		# This might yield better results if we also specialize it by
		# manufacturer
		self.wordMap = wordMap = defaultdict(list)
		for product in self.products:
			wordMap[normalize(product.family)].append( product )
			wordMap[normalize(product.model)].append( product )

		numProducts = float(len(self.products))
		self.wordScore = dict( 
			(word, -log( len(wordMap[word]) / numProducts )) 
			for word in wordMap.keys() )

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
		if cost < 50:
			p = 0.3
		if cost < 100:
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
		if not self.isCamera( listing ) or listing['manufacturer'] not in self.manufacturerMap:
			return {}
		manufacturer = self.manufacturerMap[ listing['manufacturer'] ]

		results = dict( (product,0) for product in self.products if product.manufacturer == manufacturer )

		for n in xrange(1,3):

			for word in ngrams(n, listing['title'].split()):

				dampener = self.listWordScore[word] if word in self.listWordScore else 1
				if word in self.wordMap:
					wordProducts = self.wordMap[word]
					scoreIncr = self.wordScore[word]

					for product in wordProducts:
						if product.manufacturer == manufacturer:
							results[product] += scoreIncr * dampener

		return results

	def reconcile(self, score_threshold=35):
		"""Reconciles listings with products."""
		matchresults = defaultdict(list)
		for listing in self.listings:
			results = self.findCandidateProducts( listing )
			hits = sorted( results.items(), key=lambda (p,s): s )
			if hits:
				product, score = hits[-1]
				if score > score_threshold:
					matchresults[product.product_name].append( listing)

		return matchresults

	def pruneByCost(self, matchresults, sanity_factor = 1.5, sd_threshold = 0.1 ):
		"""Makes the assumption that similar products will be somewhat similarly priced,
		and that great outliers are likely different products instead.

		Items will only be pruned if: 
		  * there are more than two listings
		  * there is a sufficient spread in prices ( sd >= mean * sd_threshold ), 
		  * the listing's cost is more than sanity_factor * sd less than the mean price. 

		Experimentally, high-priced outliers were rarely false positives.

		This trades false negatives for reduced false positives.

		Modifies the matchresults dict in place."""

		# Improved heuristics would distinguish between full kits and body only
		# (Boîtier seulement, nur Gehäuse, etc.) where applicable.
		for product, listings in matchresults.items():
			if len( listings ) < 3:
				continue
			costs = map( getCost, listings )
			mean = sum(costs) / len(costs)
			sd = sqrt( sum( (cost - mean)**2 for cost in costs ) / (len(costs)-1) )
			if sd < mean * sd_threshold:
				continue
			if self.debug:
				removed = [(listing,cost) for (listing, cost) in zip(listings, costs) if mean - cost >= sd * sanity_factor]
				if removed:
					print product, len(listings), mean, sd, removed
			listings = [listing for (listing, cost) in zip(listings, costs) if mean - cost < sd * sanity_factor]
			matchresults[product] = listings
		return matchresults

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
	matchresults = reconciler.reconcile(args.score_threshold)
	reconciler.pruneByCost( matchresults, args.sanity_factor, args.sd_threshold)
	json.dump( matchresults, args.output, sort_keys=True, indent=4 if args.pretty_print else None )
	args.output.write("\n")
