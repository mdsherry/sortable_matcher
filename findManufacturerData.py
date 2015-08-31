import json
from collections import defaultdict, Counter, namedtuple
def jsonToList( fname ):
	f = open(fname, 'rt')
	results = []
	for line in f:
		results.append( json.loads( line ) )
	return results


products = jsonToList('products.txt')
prodmanu = set()
for product in products:
	prodmanu.add( product['manufacturer'])

listings = jsonToList('listings.txt')
listingmanu = set()
for listing in listings:
	listingmanu.add( listing['manufacturer'])

print "{} prodmanus; {} listingmanus. {} prod only; {} listing only".format(
	len( prodmanu ), len( listingmanu ), len( prodmanu - listingmanu ), len( listingmanu - prodmanu ) )

