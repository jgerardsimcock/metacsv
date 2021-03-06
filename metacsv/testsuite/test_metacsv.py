#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `metacsv` module."""

from __future__ import (
    absolute_import,
    division, print_function, with_statement,
    unicode_literals
)

import glob
import os
import xarray as xr
import pandas as pd
import numpy as np
import shutil
import json
import subprocess
import locale

import metacsv
from . import unittest
from . import helpers

from .._compat import text_type

class VersionError(ValueError):
    pass


class MetacsvTestCase(unittest.TestCase):
    testdata_prefix = 'metacsv/testsuite/test_data'
    test_tmp_prefix = 'metacsv/testsuite/tmp'

    def setUp(self):
        if not os.path.isdir(self.test_tmp_prefix):
            os.makedirs(self.test_tmp_prefix)

    def test_read_csv(self):
        """CSV Test 1: Check DataFrame data for CSVs with and without yaml headers"""

        csv1 = metacsv.read_csv(os.path.join(
            self.testdata_prefix, 'test1.csv'))
        csv2 = pd.read_csv(os.path.join(self.testdata_prefix, 'test2.csv'))

        csv1.__repr__()
        csv2.__repr__()

        self.assertTrue(
            (csv1.values == csv2.set_index('ind').values).all().all())

    def test_coordinate_conversion_to_xarray(self):
        '''CSV Test 2: Make sure only base coordinates are used in determining xarray dimensionality'''

        df = metacsv.read_csv(os.path.join(self.testdata_prefix, 'test6.csv'))

        df_str = df.__repr__()

        self.assertEqual(df.to_xarray().isnull().sum().col1, 0)
        self.assertEqual(df.to_xarray().isnull().sum().col2, 0)

        # Test automatic coords assignment
        df = metacsv.read_csv(os.path.join(
            self.testdata_prefix, 'test5.csv'), squeeze=True)
        del df.coords

        ds = df.to_xarray()

        self.assertNotEqual(len(df.shape), len(ds.shape))
        self.assertEqual(df.shape[0], ds.shape[0])
        self.assertTrue(ds.shape[1] > 1)

    def test_for_series_attributes(self):
        '''CSV Test 3: Ensure read_csv preserves attrs with squeeze=True conversion to Series

        This test is incomplete - a complete test would check that attrs are preserved
        when index_col is not set and the index is set by coords. Currently, this 
        does not work.
        '''

        s = metacsv.read_csv(os.path.join(
            self.testdata_prefix, 'test5.csv'), squeeze=True, index_col=[0, 1])

        s.__repr__()

        self.assertTrue(hasattr(s, 'attrs') and ('author' in s.attrs))
        self.assertEqual(s.attrs['author'], 'series creator')

    def test_write_and_read_equivalency(self):
        '''CSV Test 4: Ensure data and attr consistency after write and re-read'''

        csv1 = metacsv.read_csv(os.path.join(
            self.testdata_prefix, 'test1.csv'))
        csv1.attrs['other stuff'] = 'this should show up after write'
        csv1['new_col'] = (np.random.random((len(csv1), 1)))
        tmpfile = os.path.join(self.test_tmp_prefix, 'test_write_1.csv')
        csv1.to_csv(tmpfile)

        csv2 = metacsv.read_csv(tmpfile)

        csv1.__repr__()
        csv2.__repr__()

        self.assertTrue((abs(csv1.values - csv2.values) < 1e-7).all().all())
        self.assertEqual(csv1.coords, csv2.coords)
        self.assertEqual(csv1.variables, csv2.variables)

        with open(tmpfile, 'w+') as tmp:
            csv1.to_csv(tmp)

        with open(tmpfile, 'r') as tmp:
            csv2 = metacsv.read_csv(tmp)

        self.assertTrue((abs(csv1.values - csv2.values) < 1e-7).all().all())
        self.assertEqual(csv1.coords, csv2.coords)
        self.assertEqual(csv1.variables, csv2.variables)

    def test_series_conversion_to_xarray(self):
        '''CSV Test 5: Check conversion of metacsv.Series to xarray.DataArray'''

        csv1 = metacsv.read_csv(os.path.join(
            self.testdata_prefix, 'test5.csv'), squeeze=True)
        self.assertEqual(len(csv1.shape), 1)

        self.assertEqual(csv1.to_xarray().shape, csv1.shape)
        self.assertTrue((csv1.to_xarray().values == csv1.values).all())

    def test_command_line_converter(self):

        convert_script = 'metacsv.scripts.convert'

        testfile = os.path.join(self.testdata_prefix, 'test6.csv')
        newname = os.path.splitext(os.path.basename(testfile))[0] + '.nc'
        outfile = os.path.join(self.test_tmp_prefix, newname)

        p = subprocess.Popen(
            ['python', '-m', convert_script, 'netcdf', testfile, outfile],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE)

        out, err = p.communicate()
        if len(err.strip()) != 0:
            print(err.strip().decode(locale.getpreferredencoding()))
        self.assertEqual(len(err.strip()), 0)

        df = metacsv.read_csv(testfile)

        with xr.open_dataset(outfile) as ds:
            self.assertTrue((abs(df.values - ds.to_dataframe().set_index(
                [i for i in df.coords if i not in df.base_coords]).values) < 1e-7).all().all())

    def test_command_line_version_check(self):
        def get_version(readfile):
            version_check_script = 'metacsv.scripts.version'

            p = subprocess.Popen(
                ['python', '-m', version_check_script, readfile],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE)

            out, err = p.communicate()
            if len(err) != 0:
                raise VersionError(err.strip())
            else:
                return out.strip().decode(locale.getpreferredencoding())

        testfile = os.path.join(self.testdata_prefix, 'test6.csv')

        with self.assertRaises(VersionError):
            get_version(testfile)

        testfile = os.path.join(self.testdata_prefix, 'test5.csv')
        df = metacsv.read_csv(testfile)

        self.assertEqual(get_version(testfile), df.attrs['version'])

    def test_xarray_variable_attribute_persistence(self):
        testfile = os.path.join(self.testdata_prefix, 'test6.csv')
        self.assertTrue(metacsv.read_csv(
            testfile).to_xarray().col1.attrs['unit'], 'wigits')

    def test_change_dims(self):
        testfile = os.path.join(self.testdata_prefix, 'test6.csv')
        df = metacsv.read_csv(testfile)

        # Test DataFrame._constructor_sliced
        series = df[df.columns[0]]
        self.assertTrue(hasattr(series, 'coords'))

        # Test Series._constructor_expanddims
        df2 = metacsv.DataFrame({df.columns[0]: series})
        self.assertTrue(hasattr(df2, 'coords'))

        # Test DataFrame._constructor_expanddims
        panel = metacsv.Panel({'df': df})
        self.assertTrue(hasattr(panel, 'coords'))

        # Test Panel._constructor_sliced
        df3 = panel['df']
        self.assertTrue(hasattr(df3, 'coords'))

    def test_standalone_properties(self):

        df = metacsv.read_csv(os.path.join(self.testdata_prefix, 'test3.csv'))

        df.columns = ['index', 'column1', 'column2']
        df.set_index('index', inplace=True)

        variables = metacsv.core.internals.Variables({
            'column1': {
                'units': 'wigits'
            },
            'column2': {
                'units': 'wigits'
            }})

        df.variables = variables

        self.assertEqual(df.variables, variables)
        self.assertEqual(df.variables.__repr__(), variables.__repr__())
        self.assertEqual(df.variables[df.columns[1]]['units'], 'wigits')

        attrs = metacsv.core.internals.Attributes()
        self.assertEqual(attrs, None)
        self.assertFalse('author' in attrs.copy())

        with self.assertRaises(KeyError):
            del attrs['author']

        with self.assertRaises(KeyError):
            err = attrs['author']

        with self.assertRaises(KeyError):
            err = attrs.get('author')

        self.assertEqual(attrs.get('author', None), None)

        with self.assertRaises(ValueError):
            err = attrs.get('author', 1, 2)

        self.assertEqual(attrs.pop('author', None), None)

        with self.assertRaises(KeyError):
            err = attrs.pop('author')

        with self.assertRaises(ValueError):
            err = attrs.pop('author', 1, 2)

        self.assertEqual(attrs, None)
        self.assertEqual(attrs.__repr__(), '<Empty Attributes>')

        attrs['author'] = 'My Name'
        attrs['contact'] = 'me@email.com'

        self.assertEqual(attrs.pop('author', None), 'My Name')
        self.assertEqual(attrs.pop('author', None), None)

        df.attrs.update(attrs)
        df.attrs.update({'project': 'metacsv'})

        with self.assertRaises(TypeError):
            df.attrs.update(1)

        self.assertNotEqual(df.attrs, attrs)
        del df.attrs['project']
        self.assertEqual(df.attrs, attrs)

        self.assertEqual(df.attrs['contact'], 'me@email.com')
        self.assertEqual(df.attrs.get('contact'), 'me@email.com')
        self.assertEqual(df.attrs.get('other', 'thing'), 'thing')
        self.assertEqual(df.attrs.pop('contact'), 'me@email.com')
        self.assertEqual(df.attrs.pop('contact', 'nope'), 'nope')
        self.assertNotEqual(df.attrs, attrs)

        attrs['author'] = 'My Name'
        df.variables['column1'] = attrs
        self.assertEqual(df.variables['column1']['author'], 'My Name')

        var = df.variables.copy()
        self.assertEqual(df.variables, var)

        with self.assertRaises(TypeError):
            var.parse_string_var(['unit'])

        self.assertTrue('description' in var.parse_string_var('variable name [unit]'))
        self.assertEqual(var.parse_string_var('variable [ name'), 'variable [ name')
        
        with self.assertRaises(TypeError):
            df.variables = []

        del df.variables

        # Test round trip
        df2 = metacsv.read_csv(
            os.path.join(self.testdata_prefix, 'test3.csv'),
            index_col=[0], skiprows=1,
            names=['column1', 'column2'])

        df2.index.names = ['index']

        self.assertTrue((df == df2).all().all())

    def test_standalone_coords(self):

        with self.assertRaises(TypeError):
            coords = metacsv.core.internals.Coordinates({'a': 'b'}, container=[])

        coords = metacsv.core.internals.Coordinates()

        with self.assertRaises(ValueError):
            coords.update()
        
        with self.assertRaises(KeyError):
            coords['a']
            
        self.assertEqual(coords.__repr__(), '<Empty Coordinates>')

        coords.update({'a': None})
        self.assertNotEqual(coords.__repr__(), '<Empty Coordinates>')


    def test_parse_vars(self):
        df = metacsv.read_csv(
            os.path.join(self.testdata_prefix, 'test8.csv'), 
            parse_vars=True, 
            index_col=[0,1,2],
            coords={'ind1':None, 'ind2':None, 'ind3':['ind2']})

        self.assertTrue(df.hasattr(df.variables['col1'], 'description'))
        self.assertEqual(df.variables['col1']['description'], 'The first column')
        self.assertEqual(df.variables['col2']['unit'], 'digits')


    def test_parse_vars(self):

        df = metacsv.read_csv(os.path.join(
            self.testdata_prefix, 'test7.csv'), parse_vars=True, index_col=0)
        ds = df.to_xarray()

        self.assertEqual(ds.col1.attrs['description'], 'The first column')
        self.assertEqual(ds.col1.attrs['unit'], 'wigits')
        self.assertEqual(ds.col2.attrs['description'], 'The second column')
        self.assertEqual(ds.col2.attrs['unit'], 'digits')

    def test_attr_updating(self):

        df = metacsv.read_csv(os.path.join(self.testdata_prefix, 'test6.csv'))
        df.coords.update({'ind3': ['s2'], 's2': None})
        coords = df.coords

        # Send to xarray.Dataset
        ds = df.to_xarray()

        del df.coords

        # Create a similarly indexed series by
        # applying coords after the slice operation
        s = df['col1']
        s.coords = coords

        # Send to xarray.DataArray
        da = s.to_xarray()

        self.assertTrue((ds.col1 == da).all().all())

        df = metacsv.DataFrame(np.random.random((3,4)))
        df.add_coords()
        del df.coords

        df.index = pd.MultiIndex.from_tuples([('a','x'),('b','y'),('c','z')])
        df.add_coords()


    def test_converters(self):

        tmpfile = os.path.join(self.test_tmp_prefix, 'test_write_1.csv')
        tmpnc = os.path.join(self.test_tmp_prefix, 'test_write_1.nc')

        df = pd.DataFrame(np.random.random((3,4)), columns=list('abcd'))
        df.index.names = ['ind']

        attrs = {'author': 'My Name'}

        metacsv.to_csv(df, tmpfile, attrs=attrs, coords={'ind': None})
        da = metacsv.to_dataarray(df, attrs=attrs, coords={'ind': None})
        ds1 = metacsv.to_xarray(df, attrs=attrs, coords={'ind': None})
        ds2 = metacsv.to_dataset(df, attrs=attrs, coords={'ind': None})
        
        df2 = metacsv.DataFrame(df, attrs=attrs)
        df2.add_coords()

        df3 = metacsv.read_csv(tmpfile)

        self.assertEqual(df2.coords, df3.coords)

        self.assertTrue((ds1 == ds2).all().all())
        self.assertEqual(df.shape[0]*df.shape[1], da.shape[0]*da.shape[1])

        attrs = metacsv.core.internals.Attributes()
        attrs.update(da.attrs)
        self.assertEqual(df2.attrs, attrs)

        df = metacsv.read_csv(os.path.join(self.testdata_prefix, 'test6.csv'))
        ds = df.to_xarray()
        da = df.to_dataarray()
        self.assertFalse(ds.col2.isnull().any())

        attrs = df.attrs.copy()
        coords = df.coords.copy()
        variables = df.variables.copy()

        df.columns.names = ['cols']

        s = df.stack('cols')
        metacsv.to_csv(s, tmpfile, attrs={'author': 'my name'})
        s = metacsv.Series(s)
        coords.update({'cols': None})
        s.attrs = attrs
        s.coords = coords
        s.variables = variables

        s.to_xarray()
        s.to_dataarray()
        s.to_dataset()

        with self.assertRaises(TypeError):
            metacsv.to_xarray(['a','b','c'])

        metacsv.to_csv(
            os.path.join(self.testdata_prefix, 'test6.csv'), 
            tmpfile, 
            attrs={'author': 'test author'},
            variables={'col1': {'unit': 'digits'}})


        df = metacsv.read_csv(tmpfile)
        self.assertEqual(df.attrs['author'], 'test author')

        ds = metacsv.to_xarray(tmpfile)
        self.assertEqual(ds.col1.attrs['unit'], 'digits')


        metacsv.to_netcdf(tmpfile, tmpnc)
        with xr.open_dataset(tmpnc) as ds:
            self.assertEqual(ds.col1.attrs['unit'], 'digits')


    def test_assertions(self):
        fp = os.path.join(self.testdata_prefix, 'test7.csv')

        df = metacsv.read_csv(fp, parse_vars=True, 
            assertions={'attrs': {'version': 'test5.2016-05-01.01'}})

        df = metacsv.read_csv(fp, parse_vars=True, 
            assertions={'attrs': {'version': lambda x: x>'test5.2016-05-01.00'}})

        df = metacsv.read_csv(fp, parse_vars=True, 
            assertions={'variables': {'col2': {'unit': 'digits'}}})

    def test_header_writer(self):
        fp = os.path.join(self.testdata_prefix, 'test9.csv')

        attrs = {'author': 'test author', 'contact': 'my.email@isp.net'}
        coords = {'ind1': None, 'ind2': None, 'ind3': 'ind2'}
        variables = {'col1': dict(description='my first column'), 'col2': dict(description='my second column')}

        tmpheader = os.path.join(self.test_tmp_prefix, 'test_header.header')
        metacsv.to_header(tmpheader, attrs=attrs, coords=coords, variables=variables)

        df = metacsv.read_csv(fp, header_file=tmpheader)

        self.assertEqual(df.attrs, attrs)
        self.assertEqual(df.coords, coords)
        self.assertEqual(df.variables, variables)


    def tearDown(self):
        if os.path.isdir(self.test_tmp_prefix):
            shutil.rmtree(self.test_tmp_prefix)


def suite():
    from .helpers import setup_path
    setup_path()
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(MetacsvTestCase))
    return suite
