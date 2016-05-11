

import pandas as pd, numpy as np, xarray as xr
from pandas.compat import string_types
from collections import OrderedDict
from pandas.core.base import FrozenList


class GraphIsCyclicError(ValueError):
  pass

class Coordinates(object):
  '''
  Manages coordinate system for MetaDoc data containers

  :param argumentName: an example argument.
  :type argumentName: string
  :param anOptionalArg: an optional argument.
  :type anOptionalArg: string
  :returns: New instance of :class:`Metadoc`
  :rtype: Metadoc
  '''

  def __init__(self, coords={}):
    self.__set__(coords)

  def __get__(self):
    return self._coords

  def __set__(self, coords):
    self._coords, self._base_coords, self._base_dependencies = self._validate_coords(coords)

  def copy(self):
    return Coordinates(self._coords.copy())

  def get_base_coords(self):
    return self._base_coords

  @property
  def base_coords(self):
    return self.get_base_coords()


  @staticmethod
  def _validate_coords(coords):
    ''' Validate coords to test for cyclic graph '''

    if not hasattr(coords, 'iterkeys'):
      coords = OrderedDict(zip(list(coords), [None for _ in range(len(coords))]))
      return coords, FrozenList(coords.keys()), {c: set([c]) for c in coords.keys()}

    base_coords = []
    dependencies = OrderedDict([])
    base_deps = {}
    visited = set()

    def find_coord_dependencies(coord):
      if coord in visited:
        if coord not in dependencies:
          raise GraphIsCyclicError
        return

      deps = coords.pop(coord)


      if deps is None:
        base_coords.append(coord)
        dependencies[coord] = None
        base_deps[coord] = set([coord])
        visited.add(coord)

      elif isinstance(deps, string_types):
        visited.add(coord)
        find_coord_dependencies(deps)
        dependencies[coord] = set([deps])
        base_deps[coord] = base_deps[deps]

      else:
        visited.add(coord)
        dependencies[coord] = set()
        base_deps[coord] = set()
        for ele in deps:
          find_coord_dependencies(ele)
          dependencies[coord].add(ele)
          base_deps[coord] |= base_deps[ele]

    while len(coords) > 0:
      find_coord_dependencies(next(coords.iterkeys()))

    return dependencies, FrozenList(base_coords), base_deps


  def _update(self, coords):
    if not hasattr(self, '_coords'):
      _coords = {}
    else:
      _coords = self._coords.copy()

    _coords.update(coords)
    coords, base_coords, base_dependencies = self._validate_coords(_coords)

    assert len(base_coords) > 0, "Index must have at least one base coordinate"

    self._coords = coords
    self._base_coords = base_coords
    self._base_dependencies = base_dependencies



class Container(object):

  def __init__(self, coords=None, *args, **kwargs):
    '''
    Initialization method for Container objects

    :param argumentName: an example argument.
    :type argumentName: string
    :param anOptionalArg: an optional argument.
    :type anOptionalArg: string
    :returns: New instance of :class:`Metadoc`
    :rtype: Metadoc

    '''

    if coords is None:
      coords = {'index_{}'.format(i) if coord is None else coord: None for i, coord in enumerate(self.index.names)}
    self._coords = Coordinates(coords)

  @property
  def coords(self):
    return self._coords.__get__()

  @property
  def base_coords(self):
    return self._coords.base_coords

  @staticmethod
  def pull_attribute(kwargs, attrs, attr):
    data = None
    if attr in kwargs:
      data = kwargs.pop(attr)
    attrs = kwargs.get(attrs)

  @property
  def metadoc_str(self):
    return '<{} {}>'.format(type(self).__module__ + '.' + type(self).__name__, self.shape)

  @property
  def coords_str(self):
    coords_str = 'Coordinates'
    for base in self.base_coords:
      coords_str += '\n' + self.repr_coord(base, base=True)
    for coord in [c for c in self.coords if not c in self.base_coords]:
      coords_str += '\n' + self.repr_coord(coord, base=False)
    return coords_str

  @property
  def attr_str(self):
    return (
      '' if len(self.attrs) == 0 else 
      '\nAttributes\n    ' + '\n    '.join(map(lambda x: '{}: {}'.format(*x), self.attrs.items()))
      )

  def repr_coord(self, coord, base=False, maxlen=50):
    if isinstance(self.index, pd.MultiIndex):
      coord_data = self.index.levels[self.index.names.index(coord)]
    else:
      coord_data = self.index.values

    coordstr = '  * ' if base else '    '
    coordstr += '{: <10}'.format(coord)
    coordstr += ' ({})'.format(coord if base else ','.join(self.coords[coord]))
    coordstr += ' {} '.format(coord_data.dtype)

    for i, ind in enumerate(coord_data):
      if len(coordstr) + len(str(ind)) + 5 > maxlen:
        return coordstr + '...'

      if i > 0:
        coordstr += ', '

      coordstr += '{}'.format(ind)

    return coordstr

  def _get_coord_data_from_index(self, coord):
    return self.index.get_level_values(coord)


  def _get_coords_dataarrays_from_index(self):

    coords = OrderedDict()

    for coord in self.base_coords:
      coords[str(coord)] = self._get_coord_data_from_index(coord).values

    for coord in [k for k in self.coords.keys() if k not in self.base_coords]:
      deps = self.coords[coord]
      coords[str(coord)] = xr.DataArray.from_series(pd.Series(self._get_coord_data_from_index(coord), index=pd.MultiIndex.from_tuples(zip(*tuple(self._get_coord_data_from_index(dep) for dep in deps)), names=map(str, deps))))

    return coords

  def update_coords(self, coords=None):

    if coords is None:
      if not pd.isnull(self.index.names).any():
        coords, base_coords, base_dependencies = self._validate_coords(self.index.names)
      
      elif len(self.index.names) == 1 and self.index.names[0] is None:
        self.index.names = ['index']
        coords, base_coords, base_dependencies = self._validate_coords(self.index.names)

      elif pd.isnull(self.index.names).all():
        self.index.names = [coord if coord is not None else 'level_{}'.format(i) for i, coord in enumerate(self.index.names)]
        coords, base_coords, base_dependencies = self._validate_coords(self.index.names)

    self._coords._update(coords)

  def to_xarray(self):

    if len(self.shape) > 2:
      raise NotImplementedError("to_xarray not yet implemented for Panel data")

    if len(self.shape) == 1:
      coords = self._get_coords_dataarrays_from_index()
      return xr.DataArray.from_series(pd.Series(
        self.values, 
        index=pd.MultiIndex.from_tuples(
          zip(*tuple([self._get_coord_data_from_index(coord) for coord in self.base_coords])), 
          names=map(str, self.base_coords))))

    if len(self.shape) == 2:

      coords = OrderedDict()
      for coord in self.coords:
        if coord in self.base_coords: continue
        coord_data = self.reset_index([c for c in self.coords if not c in self._coords._base_dependencies[coord]], drop=False, inplace=False)[coord]
        
        coords[coord] = xr.DataArray.from_series(coord_data)

      if len(self.coords) > len(self.base_coords):
        base_df = self.copy().reset_index([c for c in self.coords.keys() if not c in self.base_coords], drop=False)
      else:
        base_df = self

      data_vars = OrderedDict([(col, xr.DataArray.from_series(base_df[col])) for col in self.columns])

      return xr.Dataset(
        data_vars=data_vars, 
        coords=coords, 
        attrs=self.attrs)
    

  def to_dataarray(self):

    if len(self.shape) > 2:
      raise NotImplementedError("to_dataset not yet implemented for Panel data")

    if len(self.shape) == 1:
      return self.to_xarray()

    if len(self.shape) == 2:
      self.columns.names = [c if c is not None else 'ind_{}'.format(len(self.index.names) + i) for i, c in enumerate(self.columns.names)]
      
      return self.unstack(self.columns.names[0]).to_dataarray()


class Attributes(object):
  def __init__(self, attrs):
    self.__set__(attrs)
  def __set__(self, attrs):
    self._attrs = attrs
  def __get__(self):
    return self._attrs


class Series(Container, pd.Series):
  '''
  MetaDoc.Series, inherrited from pandas.Series
  '''

  _metadata = [
    'attrs',       # Metadata/documentation attributes
    '_coords'       # Coordinates
  ]

  @property
  def _constructor(self):
    return Series

  @property
  def _constructor_expanddim(self):
    return DataFrame

  def __init__(self, *args, **kwargs):

    attrs = kwargs.pop('attrs', {})

    coords = attrs.pop('coords', {})
    coords.update(kwargs.pop('coords', {}))

    self.attrs = attrs

    pd.Series.__init__(self, *args, **kwargs)
    Container.__init__(self, coords=coords)

  def __repr__(self):
    series_str = pd.Series.__repr__(self)
    return (self.metadoc_str + '\n' + series_str + '\n\n' + self.coords_str + self.attr_str)
    

class Variables(object):
  def __init__(self, variables):
    self.__set__(variables)
  def __set__(self, variables):
    self._variables = variables
  def __get__(self):
    return self._variables



class DataFrame(Container, pd.DataFrame):
  '''
  MetaDoc.DataFrame, inherrited from pandas.DataFrame
  '''

  _metadata = [
    'attrs',       # Metadata/documentation attributes
    'variables',   # Column Names
    '_coords'       # Coordinates
  ]

  @property
  def _constructor(self):
    return DataFrame

  @property
  def _constructor_sliced(self):
    return Series

  @property
  def _constructor_expanddims(self):
    return Panel

  def __init__(self, *args, **kwargs):

    attrs = kwargs.pop('attrs', {})

    coords = attrs.pop('coords', {})
    variables = attrs.pop('variables', {})

    coords.update(kwargs.pop('coords', {}))
    variables.update(kwargs.pop('variables', {}))

    self.attrs = attrs

    pd.DataFrame.__init__(self, *args, **kwargs)
    Container.__init__(self, coords=coords)

    self.variables = Variables(variables)

  @property
  def var_str(self):
    return ('Variables\n' + 
      '\n'.join(['    {}'.format(v) for v in self.columns])
      )
    
  def __repr__(self):
    df_str = pd.DataFrame.__repr__(self)
    return (self.metadoc_str + '\n' + df_str + '\n\n' + self.coords_str + '\n' + self.var_str + self.attr_str)


class Panel(pd.Panel):

  _metadata = [
    'attrs',       # Metadata/documentation attributes
    '_coords'       # Coordinates
  ]

  @property
  def _constructor(self):
    return Panel

  @property
  def _constructor_sliced(self):
    return DataFrame

  def __init__(self, *args, **kwargs):

    attrs = kwargs.pop('attrs', {})

    coords = attrs.pop('coords', None)
    coords

    self.attrs = attrs
   
    pd.Series.__init__(self, *args, **kwargs)
    Container.__init__(self, coords=coords)
    
  def __repr__(self):
    panel_str = pd.Panel.__repr__(self)
    return (self.metadoc_str + '\n' + panel_str + '\n\n' + self.coords_str + self.attr_str)
