from math import log
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
	if product.model == "PEN E-PL1":
		print normalize("PEN E-PL1")
	wordMap[normalize(product.family)].append( product )
	wordMap[normalize(product.model)].append( product )
	wordMap[product.manufacturer].append( product )

numProducts = float(len(products))
wordScore = dict( 
	(word, -log( len(wordMap[word]) / numProducts )) 
	for word in wordMap.keys() )


def findCandidateProducts( listing, productsByManufacturer ):
	results = dict( (product,0) for product in products )

	for n in xrange(1,3):

		for word in ngrams(n, listing['title'].split() + listing['manufacturer'].split()):

			dampener = listWordScore[word] if word in listWordScore else 1
			if word in wordMap:
				wordProducts = wordMap[word]
				scoreIncr = wordScore[word]

				for product in wordProducts:
					if dampener * scoreIncr < 0:
						print "!!!", word, dampener, scoreIncr
					results[product] += scoreIncr * dampener
normalize(''.join(bit[i:i+n]))
	return results



for i in xrange( 30 ):	
	print listings[i]['title']
	results = findCandidateProducts( listings[i], productsByManufacturer )
	for product,score in sorted( results.items(), key=lambda (p,s): s ):
		if score > 40:
			print "\t", score, product.product_name, product.family, product.model
	print
