#!/usr/bin/env python
# -*- coding: utf-8 -*-
import unittest

import reconcile

class TestReconciler( unittest.TestCase ):

	def test_normalizer(self):
		self.assertEqual( 'canon', reconcile.normalize('canon') )
		self.assertEqual( 'NikonD90', reconcile.normalize('Nikon D90') )
		self.assertEqual( 'QV5000SX', reconcile.normalize('QV-5000SX') )
		self.assertEqual( 'QV5000SX', reconcile.normalize('QV_5000SX') )
		self.assertEqual( "PENEPL2", reconcile.normalize('PEN E-PL2') )

	def test_ngrams(self):
		testString = "GE CRE00-BL Create Design Series Digital Camera - Blue".split()
		result = list( reconcile.ngrams( 1, testString) )
		self.assertEqual( 
			["GE", "CRE00BL", "Create", "Design", "Series", "Digital", "Camera", "Blue"], result)
		result = list( reconcile.ngrams( 2, testString) )
		self.assertEqual( 
			["GECRE00BL", 
			 "CRE00BLCreate", 
			 "CreateDesign", 
			 "DesignSeries", 
			 "SeriesDigital", 
			 "DigitalCamera", 
			 "Camera", 
			 "Blue"], result)
		result = list( reconcile.ngrams( 3, testString ) )
		self.assertEqual( 
			["GECRE00BLCreate",
			 "CRE00BLCreateDesign", 
			 "CreateDesignSeries", 
			 "DesignSeriesDigital", 
			 "SeriesDigitalCamera", 
			 "DigitalCamera", 
			 "CameraBlue"], result)
	
	def test_jsonToList(self):
		input = """{"title":"LED Flash Macro Ring Light (48 X LED) with 6 Adapter Rings for For Canon/Sony/Nikon/Sigma Lenses","manufacturer":"Neewer Electronics Accessories","currency":"CAD","price":"35.99"}
{"title":"Canon PowerShot SX130IS 12.1 MP Digital Camera with 12x Wide Angle Optical Image Stabilized Zoom with 3.0-Inch LCD","manufacturer":"Canon Canada","currency":"CAD","price":"199.96"}
{"title":"Canon PowerShot SX130IS 12.1 MP Digital Camera with 12x Wide Angle Optical Image Stabilized Zoom with 3.0-Inch LCD","manufacturer":"Canon Canada","currency":"CAD","price":"209.00"}
"""
		import StringIO
		io = StringIO.StringIO(input)

		result = reconcile.jsonToList( io )

		self.assertEqual( 3, len( result ) )
		for i, row in enumerate( result ):
			self.assertEqual( 
				['currency', 'manufacturer', 'price', 'title'], 
				sorted( row.keys() ), 
				"Keys for row {} didn't match".format( i + 1 ) )

	def test_manufacturerNormalizer(self):
		prodmanus = ['Canon', 'Nikon', 'Konica Minolta']
		listingmanus = ['Canon', 'Canon Canada', 'Nikon', 'Sony', 'Konica Minolta', 'Minolta']
		results = reconcile.manufacturerNormalizer( listingmanus, prodmanus )

		self.assertEqual( 'Canon', results['Canon'] )
		self.assertEqual( 'Canon', results['Canon Canada'] )
		self.assertEqual( 'Nikon', results['Nikon'] )
		self.assertFalse( 'Sony' in results )
		self.assertEqual( 'Konica Minolta', results['Konica Minolta'])
		self.assertEqual( 'Konica Minolta', results['Minolta'])

	def test_pruneByCosts(self):
		reconciler = reconcile.Reconciler([], [])
		# Since pruneByCosts doesn't use the product as anything more than a key, 
		# I'll just use a string here.
		matchresults = {
			'Nikon D90': [
				{'price': 100, 'currency': 'USD'},
				{'price': 105, 'currency': 'USD'},
				{'price': 95, 'currency': 'USD'},
				{'price': 103, 'currency': 'USD'},
				{'price': 97, 'currency': 'USD'},
				{'price': 125, 'currency': 'USD'},
				{'price': 60, 'currency': 'USD'},
			]
		}
		# These entries have a mean of 97.85, and an sd of 19.4
		
		# First, let's try running with a sd_threshold high enough that we don't trigger
		reconciler.pruneByCost( matchresults, 1.5, 0.25 )
		self.assertEqual( 7, len( matchresults['Nikon D90']))

		# Second, we'll have a sanity factor large enough that the 60 doesn't get excluded
		reconciler.pruneByCost( matchresults, 2.5, 0.25 )
		self.assertEqual( 7, len( matchresults['Nikon D90']))		

		# Finally, with a sanity factory of 1.5, this means any items below 68.75 will be dropped
		reconciler.pruneByCost( matchresults, 1.5, 0.1 )
		self.assertEqual( 6, len( matchresults['Nikon D90']))

		for price in (result['price'] for result in matchresults['Nikon D90']):
			self.assertNotEqual( 60, price )

if __name__ == '__main__':
	unittest.main()
