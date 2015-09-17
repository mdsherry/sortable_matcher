#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
from math import log, sqrt
import json
from collections import defaultdict, Counter, namedtuple
import os.path
import sys

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
	
	listing_manufacturers = set(m.upper() for m in listing_manufacturers)
	def matches( product_bit, listing_bits ):
		return any( listing_bit.startswith( product_bit) for listing_bit in listing_bits )

	results = {}
	for product_manufacturer in product_manufacturers:
		# Processed will keep track of which listing manufacturers we've
		# handled this time around so that we can avoid checking them
		# again in the future.
		# We need to store them and remove them at the end to avoid
		# modifying the set as we iterate over it.
		processed = set()
		ucase_product_manufacturer = product_manufacturer.upper()

		# Regretable truncation to match more cases
		if ucase_product_manufacturer == 'FUJIFILM':
			ucase_product_manufacturer = 'FUJI'

		for listing_manufacturer in listing_manufacturers:
			if any( matches( bit, listing_manufacturer.split() ) for bit in ucase_product_manufacturer.split() ):
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
	return s.upper().replace(" ", '').replace('_','').replace('-','')

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
		
		if self.debug:
			listing['score'] = p
		
		return p >= 0.5

	def findCandidateProducts( self, listing ):
		"""Ranks products based on how many characteristics they share
		with the listing.

		Returns a dictionary mapping product to score."""
		if not self.isCamera( listing ) or listing['manufacturer'].upper() not in self.manufacturer_map:
			listing['no-manufacturer'] = listing['manufacturer'].upper() not in self.manufacturer_map
			return {}
		manufacturer = self.manufacturer_map[ listing['manufacturer'].upper() ]
		word_map, word_score = self.words_by_manufacturer[manufacturer]
		results = defaultdict( float )

		for n in xrange(1,3):

			for word in ngrams(n, listing['title'].split()):
				# The theory behind 'dampener' is that words that appear frequently
				# in the corpus are more likely to be accidental occurrences, rather
				# than instances of a model/family name. A good example is the
				# Leica Digilux Zoom, where zoom is a word that appears frequently
				# in descriptions.
				#
				# I suspect, however, that it might be too efficient, and be leading
				# to more false negatives than is warrented.
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
		misses = []
		for listing in self.listings:
			results = self.findCandidateProducts( listing )
			hits = sorted( results.items(), key=lambda (_,s): s )
			if hits:
				product, score = hits[-1]
				
				if self.debug:
					listing['match_score']  = score
				
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
					
				else:
					misses.append( listing )
			else:
				listing['no-hits'] = True
				misses.append( listing)

		return match_results, misses

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

def open_or_die( fname ):
	if os.path.exists( fname ):
		return open( fname, 'rt' )
	sys.stderr.write("Could not find file {}. Quitting.\n".format( fname ) )
	sys.exit(-1)

if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument('--score-threshold', type=int, default=35,
		help="Score threshold for a product to be considered a match to a listing. Default: 25")
	parser.add_argument("--sd-threshold", type=float, default=0.1, 
		help="Minimum ratio of standard deviation to mean to cull suspiciously inexpensive matches. Default: 0.1")
	parser.add_argument("--sanity-factor", type=float, default=1.5, 
		help="Matches more than this number times the standard deviation will be removed. Default: 1.5")
	parser.add_argument("--debug", action="store_true", help="Enable additional debugging output")
	parser.add_argument("--listings", type=argparse.FileType('rt'), default=None,
		help="JSON file containing listings. Default: listings.txt")
	parser.add_argument("--products", type=argparse.FileType('rt'), default=None,
		help="JSON file containing products. Default: products.txt")
	parser.add_argument("--output", type=argparse.FileType('wt'), default='-',
		help="File to write reconciled output to. Default: stdout")
	parser.add_argument("--pretty-print", action="store_true", 
		help="Pretty-print output")
	parser.add_argument("--track-misses", action="store_true", help="Output information to track listings unmatched with products. Turns on debugging.")

	args = parser.parse_args()
	if args.listings is None:
		args.listings = open_or_die( 'listings.txt' )
	if args.products is None:
		args.products = open_or_die( 'products.txt' )
		
	listings = jsonToList(args.listings)
	products = jsonToList(args.products)

	reconciler = Reconciler( listings, products, debug=args.debug or args.track_misses)
	match_results, misses = reconciler.reconcile(args.score_threshold)
	reconciler.pruneByCost( match_results, args.sanity_factor, args.sd_threshold)
	for product, matches in match_results.items():
		args.output.write( '{{"product_name": {product}, "listings": {matches}}}\n'.format( 
			product=json.dumps( product ), 
			matches=json.dumps( matches, indent=4 if args.pretty_print else None ) ) )
	
	if args.track_misses:
		# There are a couple of cheap cameras (~$30) that get accidentally classified as 
		# accessories.
		accessories = [m for m in misses if 'score' in m and m['score'] < 0.5]
		with open('accessories.json', 'wt') as f:
			json.dump( accessories,f, indent=4)
		print "# Accessories:", len(accessories)
		misses = [m for m in misses if 'score' not in m or m['score'] >= 0.5]

		# There were previously many false negatives, mostly due to Fuji and 
		# Sigmatek (vs Sigma), as well as case issues. At a glance, there seem to be
		# no more false negatives here.
		nomanu = [m for m in misses if 'no-manufacturer' in m and m['no-manufacturer']]
		with open('no-manufacturer.json', 'wt') as f:
			json.dump(nomanu,f, indent=4)
		print "# No manufacturer:", len(nomanu)
		misses = [m for m in misses if 'no-manufacturer' not in m]
		
		# These are cases where we failed to guess even one product match.
		# Many of these are cases where there legitimately are no matching products.
		# In other cases, it may be because the model in the listing is missing
		# a portion of the model name (e.g. D300 instead of D300S), or sometimes
		# have extra bits that aren't part of the model name (e.g. DSC-T99/G)
		# However, such is the nature of model names, I can't tell at a glance
		# whether these are actually false negatives, or separate model sub-lines.
		# (Previously, there were also a number of false negatives due to
		# differences in case.)
		nohits = [m for m in misses if 'no-hits' in m]
		with open('no-hits.json', 'wt') as f:
			json.dump(nohits,f, indent=4)
		print "# No hits:", len(nohits)
		misses = [m for m in misses if 'no-hits' not in m]
		
		# This is the trickiest category to resolve, and the easiest to influence.
		# The lower the score threshold, the fewer false negatives, but the more 
		# false positives. Changes in how the entropy of model names is calculated
		# ended up lowering a lot of scores; I've shifted the threshold from 35 to 25
		# and the result is a lot more matches.
		# TODO: Examine results and double-check new matches
		scoretoolow = sorted([m for m in misses if m['match_score'] < args.score_threshold], key=lambda m:m['match_score'],reverse=True)
		with open('low_score.json', 'wt') as f:
			json.dump(scoretoolow,f, indent=4)
		print "# Score too low:", len(scoretoolow)
		misses = [m for m in misses if m['match_score'] >= args.score_threshold]
		
		with open('misses.json', 'wt') as f:
			json.dump( misses, f)
		print "# Remainder:", len(misses)
		
		print "# Matched:", sum( len(v) for v in match_results.values() )
		
