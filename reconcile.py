
from math import log, sqrt
import json
from collections import defaultdict, Counter, namedtuple
def jsonToList( fname ):
	f = open(fname, 'rt')
	results = []
	for line in f:
		results.append( json.loads( line ) )
	return results

listings = jsonToList('listings.txt')
products = jsonToList('products.txt')
Product = namedtuple('Product', 'product_name manufacturer model family announced_date')

def manufacturerNormalizer(listings, products):
	prodmanu = set()
	for product in products:
		prodmanu.add( product['manufacturer'])
	listingmanu = set()
	for listing in listings:
		listingmanu.add( listing['manufacturer'])

	results = {}
	for product in prodmanu:
		for listing in listingmanu:
			if any( bit in listing.split() for bit in product.split() ):
				results[listing] = product

	return results

manufacturerMap = manufacturerNormalizer(listings, products)

def sortByKey( items, key ):
	results = defaultdict(list)
	for item in items:
		results[item[key]].append( item )
	return results

productsByManufacturer = sortByKey(products, 'manufacturer')

products = [ Product( 
		p['product_name'], 
		p['manufacturer'], 
		p['model'], 
		p['family'] if 'family' in p else '', 
		p['announced-date']) for p in products]

def ngrams( n, bit):
	for i in xrange( len(bit) - n + 1):
		result = normalize(''.join(bit[i:i+n]))
		if not result.strip():
			continue
		yield result

wordCommonality = defaultdict(int)

def normalize(s):
	return s.replace(" ", '').replace('_','').replace('-','')

for listing in listings:
	for n in xrange(1,3):
		for word in ngrams(n, listing['title'].split()):
			wordCommonality[word] += 1
howmanylistings = float(len(listings))
listWordScore = dict( 
	(word, -log( wordCommonality[word] / howmanylistings )) 
	for word in wordCommonality.keys() )

wordMap = defaultdict(list)
wordScore = defaultdict(float)

for product in products:
	wordMap[normalize(product.family)].append( product )
	wordMap[normalize(product.model)].append( product )

numProducts = float(len(products))
wordScore = dict( 
	(word, -log( len(wordMap[word]) / numProducts )) 
	for word in wordMap.keys() )

def getCost( listing ):
	currencyRatios = { 'USD': 1, 'CAD': 0.75, 'EUR': 1.1, 'GBP': 1.5 }
	cost = float( listing['price'] ) * currencyRatios[listing['currency']]
	return cost

def isCamera(listing):
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
	if 'BATTERY FOR' in title:
		p -= 0.3
	if 'OPTICAL ZOOM' in title:
		p += 0.3
	if ' FOR ' in title:
		p -= 0.2
	if ' WITH ' in title:
		p += 0.2
	return p >= 0.5

def findCandidateProducts( listing, productsByManufacturer ):
	if not isCamera( listing ) or listing['manufacturer'] not in manufacturerMap:
		return {}
	manufacturer = manufacturerMap[ listing['manufacturer'] ]

	results = dict( (product,0) for product in products if product.manufacturer == manufacturer )

	for n in xrange(1,3):

		for word in ngrams(n, listing['title'].split()):

			dampener = listWordScore[word] if word in listWordScore else 1
			if word in wordMap:
				wordProducts = wordMap[word]
				scoreIncr = wordScore[word]

				for product in wordProducts:
					if product.manufacturer == manufacturer:
						results[product] += scoreIncr * dampener

	return results

matchresults = defaultdict(list)
for listing in listings:
	results = findCandidateProducts( listing, productsByManufacturer )
	hits = sorted( results.items(), key=lambda (p,s): s )
	if hits:
		product, score = hits[-1]
		if score > 30:
			matchresults[product.product_name].append( listing)

sanity_factor = 1.5
for product, listings in matchresults.items():
	if len( listings ) < 3:
		continue
	costs = map( getCost, listings )
	mean = sum(costs) / len(costs)
	sd = sqrt( sum( (cost - mean)**2 for cost in costs ) / (len(costs)-1) )
	if sd == 0:
		continue
	# if sd < mean * 0.1:
	# 	continue
	removed = [(listing,cost) for (listing, cost) in zip(listings, costs) if mean - cost >= sd * sanity_factor]
	if removed:
		print product, len(listings), mean, sd, removed
	listings = [listing for (listing, cost) in zip(listings, costs) if mean - cost < sd * sanity_factor]
	matchresults[product] = listings
print json.dumps( matchresults, sort_keys=True, indent=4 )
