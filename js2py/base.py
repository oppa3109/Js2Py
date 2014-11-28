'''Most important file in Js2Py implementation: PyJs class - father of all PyJs objects'''
from copy import copy
import re
from translators import translator
from utils.injector import fix_js_args
from translators.jsparser import OP_METHODS
from types import FunctionType
import traceback

def MakeError(name, message):
    """Returns PyJsException with PyJsError inside"""
    return JsToPyException(ERRORS[name](Js(message)))

def Js(val):
    '''Converts Py type to PyJs type'''
    if isinstance(val, PyJs):
        return val
    elif val is None:
        return undefined
    elif isinstance(val, basestring):
        return PyJsString(val, StringPrototype)
    elif isinstance(val, bool):
        return true if val else false
    elif isinstance(val, float) or isinstance(val, int) or isinstance(val, long):
        return PyJsNumber(float(val), NumberPrototype)
    elif isinstance(val, tuple): # convert to arguments
        return val # todo later
    elif isinstance(val, FunctionType):
        return PyJsFunction(val, FunctionPrototype)
    elif isinstance(val, dict): # convert to object
         temp = PyJsObject({}, ObjectPrototype)
         for k, v in val.iteritems():
             temp.put(k, v)
         return temp
    elif isinstance(val, list): #Convert to array
        return PyJsArray(val, ArrayPrototype)
    else:
        raise RuntimeError('Cant convert python type to js')

def Type(val):
    try:
        return val.TYPE
    except:
        raise RuntimeError('Invalid type: '+str(val))

def is_data_descriptor(desc):
    return desc and ('value' in desc or 'writable' in desc)
    
def is_accessor_descriptor(desc):
    return desc and ('get' in desc or 'set' in desc)
    
def is_generic_descriptor(desc):
    return desc and not (is_data_descriptor(desc) or is_accessor_descriptor(desc))


this = globals()  # this should be a global object...

##############################################################################

class PyJs:
    PRIMITIVES =  {'String', 'Number', 'Boolean', 'Undefined', 'Null'}
    TYPE = 'Object'
    Class = None
    extensible = True
    prototype = None
    own = {}
    GlobalObject = None
    value = None
    
    def __init__(self, value=None, prototype=None, extensible=False):
        '''Constructor for Number String and Boolean'''
        if self.Class=='String' and not isinstance(value, basestring):
            raise TypeError
        if self.Class=='Number':
            if not isinstance(value, float):
                if not (isinstance(value, int) or isinstance(value, long)):
                    raise TypeError
                value = float(value)
        if self.Class=='Boolean' and not isinstance(value, bool):
            raise TypeError
        self.value = value
        self.extensible = extensible
        self.prototype = prototype
        self.own = {}
        
    def is_undefined(self):
        return self.Class=='Undefined'
    
    def is_null(self):
        return self.Class=='Null'
        
    def is_primitive(self):
        return Type(self) in self.PRIMITIVES
    
    def is_object(self):
        return not self.is_primitive()
    
    def is_callable(self):
        return hasattr(self, 'call')
    
    def get_own_property(self, prop):
        return self.own.get(prop)
    
    def get_property(self, prop):
        cand = self.get_own_property(prop)
        if cand:
            return cand
        if self.prototype is not None:
            return self.prototype.get_property(prop)
    
    def get(self, prop): #external use!
         #prop = prop.value
         if self.Class=='Undefined' or self.Class=='Null':
             raise MakeError('TypeError', 'Undefiend and null dont have properties!')
         if not isinstance(prop, basestring):
             prop = prop.to_string().value
         if not isinstance(prop, basestring): raise RuntimeError('Bug')
         cand = self.get_property(prop)
         if cand is None:
             return Js(None)
         if is_data_descriptor(cand): 
             return cand['value']
         if cand['get'].is_undefined():
             return cand['get']
         return cand['get'].call(self)
    
    def can_put(self, prop):  #to check
        desc = self.get_own_property(prop)
        if desc: #if we have this property
            if is_accessor_descriptor(desc):
                return desc['set'].is_callable() # Check if setter method is defined           
            else:  #data desc 
                return desc['writable']
        if self.prototype is not None:
            return self.extensible
        inherited = self.get_property(prop)
        if inherited is None:
            return self.extensible
        if is_accessor_descriptor(inherited):
            return not inherited['set'].is_undefined()
        elif self.extensible:
            return inherited['writable']
        return False
            
    
    def put(self, prop, val, op=None):  #external use!
        '''Just like in js: self.prop op= val
           for example when op is '+' it will be self.prop+=val
           op can be either None for simple assignment or one of:
           * / % + - << >> & ^ |'''
        if self.Class=='Undefined' or self.Class=='Null':
             raise MakeError('TypeError', 'Undefiend and null dont have properties!')
        if not isinstance(prop, basestring):
             prop = prop.to_string().value
        #we need to set the value to the incremented one
        if op is not None:
            val = getattr(self.get(prop), OP_METHODS[op])(val)
        if not self.can_put(prop):
            return val
        own_desc = self.get_own_property(prop)
        if is_data_descriptor(own_desc):
            if self.Class=='Array': #only array has different define_own_prop
                self.define_own_property(prop, {'value':val})
            else:
                self.own[prop]['value'] = val
            return val
        desc = self.get_property(prop)
        if is_accessor_descriptor(desc):
            desc['set'].call(self, (val,))
        else:
            new = {'value' : val,
                   'writable' : True,
                   'configurable' : True,
                   'enumerable' : True}
            if self.Class=='Array':
                self.define_own_property(prop, new)
            else:
                self.own[prop] = new
        return val
                
    def has_property(self, prop):
        return self.get_property(prop) is not None
    
    def delete(self, prop):
        if not isinstance(prop, basestring):
            prop = prop.to_string().value
        desc = self.get_own_property(prop)
        if desc is None: 
            return Js(True)
        if desc['configurable']:
            del self.own[prop]
            return Js(True)
        return Js(False)
    
    def default_value(self, hint=None):
        order = ['toString', 'valueOf']
        if hint=='Number' or (hint is None and self.Class=='Date'):
            order.reverse()
        for meth_name in order:
            method = self.get(meth_name)
            if method is not None and method.is_callable():
                cand = method.call(self)
                if cand.is_primitive():
                    return cand
        raise MakeError('TypeError', 'Cannot convert object to primitive value')
        
    def define_own_property(self, prop, desc): #Internal use only. External through Object
        # prop must be a Py string. Desc is either a descriptor or accessor.
        #Messy method -  raw translation from Ecma spec to prevent any bugs.
        current = self.get_own_property(prop)

        extensible = self.extensible
        DEFAULT_DATA_DESC = {'value': undefined, #undefined
                             'writable': False,
                             'enumerable': False,
                             'configurable': False}
        DEFAULT_ACCESSOR_DESC = {'get': undefined, #undefined
                                 'set': undefined, #undefined
                                 'enumerable': False,
                                 'configurable': False}
        if not current: #We are creating a new property
            if not extensible:
                return False
            if is_data_descriptor(desc) or is_generic_descriptor(desc):
                DEFAULT_DATA_DESC.update(desc)
                self.own[prop] = DEFAULT_DATA_DESC
            else:
                DEFAULT_ACCESSOR_DESC.update(desc)
                self.own[prop] = DEFAULT_ACCESSOR_DESC
            return True
        # todo make sure that == is a right comparison.
        if not desc or desc==current: #We dont need to change anything.
            return True
        configurable = current['configurable']  
        if not configurable:  #Prevent changing configurable or enumerable
            if desc.get('configurable'):
                return False
            if 'enumerable' in desc and desc['enumerable']!=current['enumerable']:
                return False
        if is_generic_descriptor(desc):
            pass
        elif is_data_descriptor(current)!=is_data_descriptor(desc):
            if not configurable:
                return False
            if is_data_descriptor(current):
                del current['value']
                del current['writable']
                current['set'] = undefined #undefined
                current['get'] = undefined #undefined
            else:
                del current['set']
                del current['get']
                current['value'] = undefined #undefined
                current['writable'] = False 
        elif is_data_descriptor(current) and is_data_descriptor(desc):
            if not configurable:
                if not current['writable'] and desc['writable']:
                    return False
            if not current['writable'] and 'value' in desc and current['value']!=desc['value']:
                return False
        elif is_accessor_descriptor(current) and is_accessor_descriptor(desc):
            if not configurable:
                if 'set' in desc and desc['set'] is not current['set']:
                    return False
                if 'get' in desc and desc['get'] is not current['get']:
                    return False
        current.update(desc)
        return True

    #these methods will work only for Number class
    def is_infinity(self):
        assert self.Class=='Number'
        return abs(self.value)==float('inf')

    def is_nan(self):
        assert self.Class=='Number'
        return self.value!=self.value #nan!=nan evaluates to true

    #todo fix increments
    def PostInc(self):
        self.value+=1
        return Js(self.value-1)

    def PreInc(self):
        self.value+=1
        return Js(self.value) # returning new instance !

    def PostDec(self):
        self.value-=1
        return Js(self.value+1)

    def PreDec(self):
        self.value-=1
        return Js(self.value)

    #Type Conversions. to_type. All must return pyjs subclass instance
    
    def to_primitive(self, hint=None):
        if self.is_primitive():
            return self
        return self.default_value(hint)
            
    def to_boolean(self):
        typ = Type(self)
        if typ=='Boolean': #no need to convert
            return self
        elif typ=='Null' or typ=='Undefined': #they are both always false
            return false
        elif typ=='Number' or typ=='String': #false only for 0, '' and NaN
            return Js(bool(self.value and self.value==self.value)) # test for nan (nan -> flase)
        else: #object -  always true
            return true
            
    def to_number(self):
        typ = Type(self)
        if typ=='Null':  #null is 0
            return Js(0)
        elif typ=='Undefined':  # undefined is NaN
            return NaN
        elif typ=='Boolean':    # 1 for true 0 for false
            return Js(int(self.value))
        elif typ=='Number':   # no need to convert
            return self
        elif typ=='String':
            s = self.value.strip() #Strip white space
            if not s: # '' is simply 0
                return Js(0)
            if 'x' in s or 'X' in s: #hex (positive only)
                try: # try to convert
                    num = int(s, 16)
                except ValueError: # could not convert > NaN
                    return NaN
                return num
            sign = 1 #get sign
            if s[0] in '+-':
                if s[0]=='-': 
                    sign = -1
                s = s[1:]
            if s=='Infinity': #Check for infinity keyword. 'NaN' will be NaN anyway.
                return Js(sign*float('inf'))
            try: #decimal try
                num = sign*float(s) # Converted
            except ValueError:
                return NaN # could not convert to decimal  > return NaN
            return Js(num) 
        else: #object -  most likely it will be NaN.
            return self.to_primitive('Number').to_number()
            
    def to_string(self):
        typ = Type(self)
        if typ=='Null':
            return Js('null')
        elif typ=='Undefined':
            return Js('undefined')
        elif typ=='Boolean':
            return Js('true') if self.value else Js('false')
        elif typ=='Number':
            if self.is_nan():
                return Js('NaN')
            elif self.is_infinity():
                sign = '-' if self.value<0 else ''
                return Js(sign+'Infinity')
            elif isinstance(self.value, long) or self.value.is_integer():  # dont print .0
                return Js(unicode(int(self.value)))
            return Js(unicode(self.value)) # accurate enough
        elif typ=='String':
            return self
        else: #object
            return self.to_primitive('String').to_string() 
            
            
    def to_object(self):
        typ = Type(self)
        if typ=='Null' or typ=='Undefined':
            raise MakeError('TypeError', 'undefined or null can\'t be converted to object')
        elif typ=='Boolean': # Unsure here... todo repair here
            return Boolean.create(self)
        elif typ=='Number': #?
            return Number.create(self)
        elif typ=='String': #? 
            return String.create(self)
        else: #object
            return self

    def to_int32(self):
        num = self.to_number()
        if num.is_nan() or num.is_infinity():
            return 0
        val = num.value
        pos_int = int(val)
        int32 = pos_int % 2**32
        return int(int32 - 2**31 if int32 > 2**31 else int32)

    def cok(self):
        """Check object coercible"""
        if self.Class in {'Undefined', 'Null'}:
            raise MakeError('TypeError', 'undefined or null can\'t be converted to object')

    def to_int(self):
        num = self.to_number()
        if num.is_nan():
            return 0
        elif num.is_infinity():
            return 10**20
        return int(num)

    def to_uint32(self):
        num = self.to_number()
        if num.is_nan() or num.is_infinity():
            return 0
        return int(int(num.value) % 2**32)

    def to_uint16(self):
        num = self.to_number()
        if num.is_nan() or num.is_infinity():
            return 0
        return int(int(num.value) % 2**16)

    def same_as(self, other):
        typ = Type(self)
        if typ!=other.Class:
            return False
        if typ=='Undefined' or typ=='Null':
            return True
        if typ=='Boolean' or typ=='Number' or typ=='String':
            return self.value==other.value
        else: #object
            return self is other #Id compare.

    #Not to be used by translation (only internal use)
    def __getitem__(self, item):
        return self.get(str(item))

    def __setitem__(self, key, value):
        self.put(str(key),  Js(value))

    def __len__(self):
        try:
            return int(self.own['length']['value'].value)
        except:
            raise TypeError('This object (%s) does not have length property'%self.Class)
    #Oprators-------------
    #Unary, other will be implemented as functions. Increments and decrements 
    # will be methods of Number class
    def __neg__(self): #-u
        return Js(-self.to_number().value)
    
    def __pos__(self): #+u
        return self.to_number()
    
    def __inv__(self): #~u    this one may be wrong! check it when implementing other bitwise ops.
        return Js(~self.to_number().value)
    
    def neg(self): # !u  cant do 'not u' :(
        return Js(not self.to_boolean().value)
    
    def __nonzero__(self): 
        return self.to_boolean().value
        
    def typeof(self): 
        if self.is_callable():
            return Js('function')
        return Js(Type(self).lower())
        
    #Bitwise operators
    #  <<, >>,  &, ^, | . I have NEVER used them in python so they can wait.
    
    # << 
    def __lshift__(self, other):
        raise NotImplementedError()
    
    # >>
    def __rshift__(self, other):
        raise NotImplementedError()
     
    # & 
    def __and__(self, other):
        raise NotImplementedError()
    
    # ^
    def __xor__(self, other): 
        raise NotImplementedError()
    
    # |
    def __or__(self, other):
        raise NotImplementedError()
        
    # Additive operators
    # + and - are implemented here
        
    # +
    def __add__(self, other):
        a = self.to_primitive()
        b = other.to_primitive()
        if a.Class=='String' or b.Class=='String':
            return Js(a.to_string().value+b.to_string().value)
        a = a.to_number()
        b = b.to_number()
        return Js(a.value+b.value)
    
    # -
    def __sub__(self, other):
        return Js(self.to_number().value-other.to_number().value)
    
    #Multiplicative operators
    # *, / and % are implemented here
    
    # *
    def __mul__(self, other):
        return Js(self.to_number().value*other.to_number().value)
        
    # /
    def __div__(self, other):
        a = self.to_number().value
        b = other.to_number().value
        if b:
            return Js(a/b)
        if not a or a!=a:
            return NaN
        return Infinity if a>0 else -Infinity
    
    # %
    def __mod__(self, other):
        a = self.to_number().value
        b = other.to_number().value
        if abs(a)==float('inf') or not b:
            return NaN
        if abs(b)==float('inf'):
            return Js(a)
        pyres = Js(a%b) #different signs in python and javascript
                        #python has the same sign as b and js has the same 
                        #sign as a.
        if a<0 and pyres.value>0:
            pyres.value -= abs(b)
        elif a>0 and pyres.value<0:
            pyres.value += abs(b)
        return Js(pyres)
        
    #Comparisons (I dont implement === and !== here, these
    # will be implemented as external functions later)
    # <, <=, !=, ==, >=, > are implemented here.
    
    def abstract_relational_comparison(self, other, self_first=True):
        ''' self<other if self_first else other<self.
           Returns the result of the question: is self smaller than other?
           in case self_first is false it returns the answer of:
                                               is other smaller than self.
           result is PyJs type: bool or undefined'''
        px = self.to_primitive('Number')
        py = other.to_primitive('Number')
        if not self_first: #reverse order
            px, py = py, px
        if not (px.Class=='String' and py.Class=='String'):
            px, py = px.to_number(), py.to_number()
            if px.is_nan() or py.is_nan():
                return undefined
            return Js(px.value<py.value) # same cmp algorithm
        else:
            # I am pretty sure that python has the same
            # string cmp algorithm but I have to confirm it
            return Js(px.value<py.value) 
        
    #<
    def __lt__(self, other): 
        res = self.abstract_relational_comparison(other, True)
        if res.is_undefined():
            return false
        return res
    
    #<=
    def __le__(self, other): 
        res = self.abstract_relational_comparison(other, False)
        if res.is_undefined():
            return false
        return res.neg() 
    
    #>=
    def __ge__(self, other): 
        res = self.abstract_relational_comparison(other, True)
        if res.is_undefined():
            return false
        return res.neg() 
    
    #>
    def __gt__(self, other): 
        res = self.abstract_relational_comparison(other, False)
        if res.is_undefined():
            return false
        return res
        
    def abstract_equality_comparison(self, other):
        ''' returns the result of JS == compare.
           result is PyJs type: bool'''
        tx, ty = self.TYPE, other.TYPE
        if tx==ty:
            if tx=='Undefined' or tx=='Null':
                return true
            if tx=='Number' or tx=='String' or tx=='Boolean':
                return Js(self.value==other.value)
            return Js(self is other) # Object
        elif (tx=='Undefined' and ty=='Null') or (ty=='Undefined' and tx=='Null'):
            return true
        elif tx=='Number' and ty=='String':
            return self.abstract_equality_comparison(other.to_number())
        elif tx=='String' and ty=='Number':
            return self.to_number().abstract_equality_comparison(other)
        elif tx=='Boolean':
            return self.to_number().abstract_equality_comparison(other)
        elif ty=='Boolean':
            return self.abstract_equality_comparison(other.to_number())
        elif (tx=='String' or tx=='Number') and other.is_object():
            return self.abstract_equality_comparison(other.to_primitive())
        elif (ty=='String' or ty=='Number') and self.is_object():
            return self.to_primitive().abstract_equality_comparison(other)
        else:
           return false
                
    #==
    def __eq__(self, other): 
        return self.abstract_equality_comparison(other)
           
    #!=
    def __ne__(self, other): 
        return self.abstract_equality_comparison(other).neg()
    
    #Other methods (instanceof)
    
    def instanceof(self, other):
        '''checks if self is instance of other'''
        if not other.hasattr('has_instance'):
            return false
        return other.has_instance(self)
        
    #iteration
    def __iter__(self):
        #Returns a generator of all own enumerable properties
        # since the size od self.own can change we need to use different method of iteration.
        # SLOW! New items will NOT show up.
        returned = {}
        cands = sorted(name for name in self.own if self.own[name]['enumerable'])
        for cand in cands:
            check = self.own.get(cand)
            if check and check['enumerable']:
                yield Js(cand)

    
    def contains(self, other):
        if not self.is_object():
            raise MakeError('TypeError',"You can\'t use 'in' operator to search in non-objects")
        return Js(self.has_property(other.to_string().value))
        
    #Other Special methods
    def __call__(self, *args):
        '''Call a property prop as a function (this will be global object).
        
        NOTE: dont pass this and arguments here, these will be added
        automatically!'''
        if not self.is_callable():
            raise  MakeError('TypeError', '%s is not a function'%self.typeof())
        return self.call(self.GlobalObject, args) # todo  value of this
    
    def __unicode__(self):
        return self.to_string().value

    def __repr__(self):
        val = self.to_string().value.encode('utf-8')
        if self.Class=='String':
            return repr(val)
        return val
    
    def callprop(self, prop, *args):
        '''Call a property prop as a method (this will be self).
        
        NOTE: dont pass this and arguments here, these will be added
        automatically!'''
        if not isinstance(prop, basestring):
            prop = prop.to_string().value
        cand = self.get(prop)
        if not cand.is_callable():
            raise  MakeError('TypeError','%s is not a function'%cand.typeof())
        return cand.call(self, args)


#Define some more classes representing operators:

def PyJsStrictEq(a, b):
    '''a===b'''
    tx, ty = Type(a), Type(b)
    if tx!=ty:
        return false
    if tx=='Undefined' or tx=='Null':
        return true
    if a.is_primitive(): #string bool and number case
        return Js(a.value==b.value)
    return Js(a is b) # object comparison
    
  
def PyJsStrictNeq(a, b):
    ''' a!==b'''
    return PyJsStrictEq(a, b).neg()
    
def PyJsBshift(a, b):
    """a>>>b"""
    return Js(0)  #NOT IMPLEMENTED YET


def PyJsComma(a, b):
    return b

class PyJsException(Exception):
    def __str__(self):
        if self.mes.Class=='Error':
            return self.mes.callprop('toString').value
        else:
            return unicode(self.mes)


PyJs.MakeError = staticmethod(MakeError)

def JsToPyException(js):
    temp = PyJsException()
    temp.mes = js
    return temp

def PyExceptionToJs(py):
    return py.mes

#Scope class it will hold all the variables accessible to user
class Scope(PyJs):
    Class = 'global'
    extensible = True
    # todo speed up
    # in order to speed up this very important class the top scope should behave differently than
    # child scopes, child scope should not have this property descriptor thing because they cant be changed anyway
    # they are all confugurable= False

    def __init__(self, scope, closure=None):
        """Doc"""
        self.prototype = closure
        if closure is None:
            # global, top level scope
            self.own = {}
            for k, v in scope.iteritems():
                # set all the global items
                self.define_own_property(k, {'value': v, 'configurable': False,
                                                'writable': False, 'enumerable': False})
        else:
            # not global, less powerful but faster closure.
            self.own = scope # simple dictionary which maps name directly to js object.

    def register(self, lval):
        # registered keeps only global registered variables
        if self.prototype is None:
            # define in global scope
            if lval in self.own:
                self.own[lval]['configurable'] = False
            else:
                self.define_own_property(lval, {'value': undefined, 'configurable': False,
                                                'writable': True, 'enumerable': True})
        elif lval not in self.own:
            # define in local scope since it has not been defined yet
            self.own[lval] = undefined # default value

    def registers(self, lvals):
        """register multiple variables"""
        for lval in lvals:
            self.register(lval)

    def put(self, lval, val, op=None):
        if self.prototype is None:
            # global scope put, simple
            return PyJs.put(self, lval, val, op)
        else:
            # trying to put in local scope
            # we dont know yet in which scope we should place this var
            if lval in self.own:
                if op: # increment operation
                     val = getattr(self.own[lval], OP_METHODS[op])(val)
                self.own[lval] = val
                return val
            else:
                #try to put in the lower scope since we cant put in this one (var wasn't registered)
                return self.prototype.put(lval, val, op)

    def force_own_put(self, prop, val, configurable=False):
        if self.prototype is None: # global scope
            self.own[prop] = {'value': val, 'writable': True, 'enumerable':True, 'configurable':configurable}
        else:
            self.own[prop] = val

    def get(self, prop):
        #note prop is always a Py String
        if self.prototype is not None:
            # fast local scope
            cand = self.own.get(prop)
            if cand is None:
                return self.prototype.get(prop)
            return cand
        # slow, global scope
        if prop not in self.own:
            raise MakeError('ReferenceError', '%s is not defined' % prop)
        return PyJs.get(self, prop)

    def delete(self, lval):
        if self.prototype is not None:
            if lval in self.own:
                return false
            return self.prototype.delete(lval)
        # we are in global scope here. Must exist and be configurable to delete
        if lval not in self.own:
            # this lval does not exist, why do you want to delete it???
            return true
        if self.own[lval]['configurable']:
            del self.own[lval]
            return true
        # not configurable, cant delete
        return false







  
##############################################################################
#Define types
    
#Object
class PyJsObject(PyJs):
    Class = 'Object'
    def __init__(self, prop_descs={}, prototype=None, extensible=True):
        self.prototype = prototype
        self.extensible = extensible
        self.own = {}
        for prop, desc in prop_descs.iteritems():
            self.define_own_property(prop, desc)
    
    
ObjectPrototype = PyJsObject()


#Function
class PyJsFunction(PyJs):
    Class = 'Function'
    def __init__(self, func, prototype=None, extensible=True, source=None):
        cand = fix_js_args(func)
        has_scope = cand is func
        func = cand
        self.argcount = func.func_code.co_argcount - 2 - has_scope
        self.code = func
        self.source = source if source else '{ [python code] }'
        self.func_name = func.func_name if not func.func_name.startswith('PyJsLvalInline') else ''
        self.extensible = extensible
        self.prototype = prototype
        self.own = {}
        #set own property length to the number of arguments
        self.define_own_property('length', {'value': Js(self.argcount), 'writable': False,
                                            'enumerable': False, 'configurable': False})
        # set own prototype
        proto = Js({})
        # constructor points to this function
        proto.define_own_property('constructor',{'value': self, 'writable': True,
                                                 'enumerable': False, 'configurable': True})
        self.define_own_property('prototype', {'value': proto, 'writable': True,
                                                 'enumerable': False, 'configurable': False})

    def construct(self, *args):
        proto = self.get('prototype')
        if not proto.is_object(): # set to standard prototype
            proto = ObjectPrototype
        obj = PyJsObject(prototype=proto)
        cand = self.call(obj, *args)
        return cand if cand.is_object() else obj
    
    def call(self, this, args=()):
        '''Calls this function and returns a result 
        (converted to PyJs type so func can return python types)
        
        this must be a PyJs object and args must be a python tuple of PyJs objects.
        
        arguments object is passed automatically and will be equal to Js(args) 
        (tuple converted to arguments object).You dont need to worry about number 
        of arguments you provide if you supply less then missing ones will be set 
        to undefined (but not present in arguments object).
        And if you supply too much then excess will not be passed 
        (but they will be present in arguments object).
        '''
        if not hasattr(args, '__iter__'):  #get rid of it later
            args = (args,)
        args = tuple(Js(e) for e in args) # this wont be needed later

        arguments = PyJsArguments(args, self) # tuple will be converted to arguments object.
        arglen = self.argcount #function expects this number of args.
        if len(args)>arglen:
            args = args[0:arglen]
        elif len(args)<arglen:
            args += (undefined,)*(arglen-len(args))
        args += this, arguments  #append extra params to the arg list
        return Js(self.code(*args))
        
    def has_instance(self, other):
        # I am not sure here so instanceof may not work lol.
        if not other.is_object():
            return false
        proto = self.get('prototype')
        if not proto.is_object():
            raise TypeError('Function has non-object prototype in instanceof check')
        while True:
            other = other.prototype
            if not other:  # todo make sure that the condition is not None or null
                return false
            if other is proto:
                return true


def Empty():
    return Js(None)

#Number
class PyJsNumber(PyJs):  #Note i dont implement +0 and -0. Just 0.
    TYPE = 'Number'
    Class = 'Number'



NumberPrototype = PyJsObject({}, ObjectPrototype)
NumberPrototype.Class = 'Number'
NumberPrototype.value = 0

Infinity = PyJsNumber(float('inf'), NumberPrototype)
NaN = PyJsNumber(float('nan'), NumberPrototype)
PyJs.NaN = NaN
PyJs.Infinity = Infinity

# This dict aims to increase speed of string creation by storing character instances
CHAR_BANK = {}
PyJs.CHAR_BANK = CHAR_BANK
#String
# Different than implementation design in order to improve performance
#for example I dont create separate property for each character in string, it would take ages.
class PyJsString(PyJs):
    TYPE = 'String'
    Class = 'String'
    extensible = False
    def __init__(self, value=None, prototype=None):
        '''Constructor for Number String and Boolean'''
        if not isinstance(value, basestring):
            raise TypeError # this will be internal error
        self.value = value
        self.prototype = prototype
        self.own = {}
         # this should be optimized because its mych slower than python str creation (about 50 times!)
        # Dont create separate properties for every index. Just
        self.own['length'] = {'value': Js(len(value)), 'writable': False,
                             'enumerable': False, 'configurable': False}
        if len(value)==1:
            CHAR_BANK[value] = self #, 'writable': False,
                               # 'enumerable': True, 'configurable': False}

    def get(self, prop):
        try:
            if not isinstance(prop, basestring):
                prop = prop.value
            char = self.value[int(prop)]
            if char not in CHAR_BANK:
                Js(char) # this will add char to CHAR BANK
            return CHAR_BANK[char]
        except ValueError:
            pass
        return PyJs.get(self, prop)

    def can_put(self, prop):
        return False

    def __iter__(self):
        for i in xrange(len(self.value)):
            yield Js(i)  # maybe create an int bank?


StringPrototype = PyJsObject({}, ObjectPrototype)
StringPrototype.Class = 'String'
StringPrototype.value = ''

CHAR_BANK[''] = Js('')

#Boolean
class PyJsBoolean(PyJs):
    TYPE = 'Boolean'
    Class = 'Boolean'

BooleanPrototype = PyJsObject({}, ObjectPrototype)
BooleanPrototype.Class = 'Boolean'
BooleanPrototype.value = False

true = PyJsBoolean(True, BooleanPrototype)
false = PyJsBoolean(False, BooleanPrototype)


#Undefined
class PyJsUndefined(PyJs):
    TYPE = 'Undefined'
    Class = 'Undefined'
    def __init__(self):
        pass

undefined = PyJsUndefined()

#Null
class PyJsNull(PyJs):
    TYPE = 'Null'
    Class = 'Null'
    def __init__(self):
        pass
null = PyJsNull()

class PyJsArray(PyJs):
    Class = 'Array'
    def __init__(self, arr=[], prototype=None):
        if arr and arr[-1] is None:
            del arr[-1]
        self.extensible = True
        self.prototype = prototype
        self.own = {'length' : {'value': Js(0), 'writable': True,
                                            'enumerable': False, 'configurable': False}}
        for i, e in enumerate(arr):
            self.define_own_property(str(i), {'value': Js(e), 'writable': True,
                                              'enumerable': True, 'configurable': True})

    def define_own_property(self, prop, desc):
        old_len_desc = self.get_own_property('length')
        old_len = old_len_desc['value'].value  #  value is js type so convert to py.
        if prop=='length':
            if 'value' not in desc:
                return PyJs.define_own_property(self, prop, desc)
            new_len =  desc['value'].to_uint32()
            if new_len!=desc['value'].to_number().value:
                raise MakeError('RangeError', 'Invalid range!')
            new_desc = {k:v for k,v in desc.iteritems()}
            new_desc['value'] = Js(new_len)
            if new_len>=old_len:
                return PyJs.define_own_property(self, prop, new_desc)
            if not old_len_desc['writable']:
                return False
            if 'writable' not in new_desc or new_desc['writable']==True:
                new_writable = True
            else:
                new_writable = False
                new_desc['writable'] = True
            if not PyJs.define_own_property(self, prop, new_desc):
                return False
            while new_len<old_len:
                old_len -= 1
                if not self.delete(str(old_len)): # if failed to delete set len to current len and reject.
                    new_desc['value'] = Js(old_len+1)
                    if not new_writable:
                        new_desc['writable'] = False
                    PyJs.define_own_property(self, prop, new_desc)
                    return False
            if not new_writable:
                self.own['length']['writable'] = False
            return True
        elif prop.isdigit():
            index = int(prop) % 2**32
            if index>=old_len and not old_len_desc['writable']:
                return False
            if not PyJs.define_own_property(self, prop, desc):
                return False
            if index>=old_len:
                old_len_desc['value'].value = index + 1
            return True
        else:
            return PyJs.define_own_property(self, prop, desc)




ArrayPrototype = PyJsArray([], ObjectPrototype)

class PyJsArguments(PyJs):
    Class = 'Arguments'
    def __init__(self, args, callee):
        self.own = {}
        self.extensible = True
        self.prototype = ObjectPrototype
        self.define_own_property('length', {'value': Js(len(args)), 'writable': True,
                                            'enumerable': False, 'configurable': False})
        self.define_own_property('callee', {'value': callee, 'writable': True,
                                            'enumerable': False, 'configurable': False})
        for i, e in enumerate(args):
            self.put(str(i), Js(e))

    def to_list(self):
        return [self.get(str(e)) for e in xrange(len(self))]


#We can define function proto after number proto because func uses number in its init
FunctionPrototype = PyJsFunction(Empty, ObjectPrototype)


# I will not rewrite RegExp engine from scratch. I will use re because its much faster.
# I have to only make sure that I am handling all the differences correctly.
class PyJsRegExp(PyJs):
    Class = 'RegExp'
    extensible = True

    def __init__(self, regexp, prototype=None):
        self.prototype = prototype
        self.glob = False
        self.ignore_case = 0
        self.multiline = 0
        if not regexp[-1]=='/':
            #contains some flags (allowed are i, g, m
            spl =  regexp.rfind('/')
            flags = set(regexp[spl+1:])
            self.value = regexp[1:spl]
            if 'g' in flags:
                self.glob = True
            if 'i' in flags:
                self.ignore_case = re.IGNORECASE
            if 'm' in flags:
                self.multiline = re.MULTILINE
        else:
            self.value = regexp[1:-1]
        try:
            # we have to check whether pattern is valid.
            # also this will speed up matching later
            self.pat = re.compile(self.value, self.ignore_case | self.multiline)
        except:
            raise PySyntaxError('Invalid RegExp pattern: %s'% repr(self.value))
        # now set own properties:
        self.own = {'source' : {'value': Js(self.value), 'enumerable': False, 'writable': False, 'configurable': False},
                    'global' : {'value': Js(self.glob), 'enumerable': False, 'writable': False, 'configurable': False},
                    'ignoreCase' : {'value': Js(bool(self.ignore_case)), 'enumerable': False, 'writable': False, 'configurable': False},
                    'multiline' : {'value': Js(bool(self.multiline)), 'enumerable': False, 'writable': False, 'configurable': False},
                    'lastIndex' : {'value': Js(0), 'enumerable': False, 'writable': True, 'configurable': False}}

    def match(self, string, pos):
        return re.match(self.pat, string[pos:])


def JsRegExp(source):
    # Takes regexp literal!
    return PyJsRegExp(source, RegExpPrototype)

RegExpPrototype = PyJsRegExp('/(?:)/', ObjectPrototype)

####Exceptions:
default_attrs = {'writable':True, 'enumerable':False, 'configurable':True}


def fill_in_props(obj, props, default_desc):
    for prop, value in props.iteritems():
        default_desc['value'] = Js(value)
        obj.define_own_property(prop, default_desc)



class PyJsError(PyJs):
    Class = 'Error'
    extensible = True
    def __init__(self, message=None, prototype=None):
        self.prototype = prototype
        self.own = {}
        if message is not None:
            self.put('message', Js(message).to_string())
            self.own['message']['enumerable'] = False

ErrorPrototype = PyJsError(Js(''), ObjectPrototype)
@Js
def Error(message):
    return PyJsError(None if message.is_undefined() else message, ErrorPrototype)
Error.create = Error
err = {'name': 'Error',
       'constructor': Error}
fill_in_props(ErrorPrototype, err, default_attrs)
Error.define_own_property('prototype', {'value': ErrorPrototype,
                                        'enumerable': False,
                                        'writable': False,
                                        'configurable': False})

def define_error_type(name):
    TypeErrorPrototype = PyJsError(None, ErrorPrototype)
    @Js
    def TypeError(message):
        return PyJsError(None if message.is_undefined() else message, TypeErrorPrototype)
    err = {'name': name,
           'constructor': TypeError}
    fill_in_props(TypeErrorPrototype, err, default_attrs)
    TypeError.define_own_property('prototype', {'value': TypeErrorPrototype,
                                                'enumerable': False,
                                                'writable': False,
                                                'configurable': False})
    ERRORS[name] = TypeError

ERRORS = {'Error': Error}
ERROR_NAMES = ['Eval', 'Type', 'Range', 'Reference', 'Syntax', 'URI']

for e in ERROR_NAMES:
    define_error_type(e+'Error')


##############################################################################
# Import and fill prototypes here.

#this works only for data properties
def fill_prototype(prototype, Class, attrs, constructor=False):
    for i in dir(Class):
        e = getattr(Class, i)
        if hasattr(e, '__func__'):
            temp = PyJsFunction(e.__func__, FunctionPrototype)
            attrs = {k:v for k,v in attrs.iteritems()}
            attrs['value'] = temp
            prototype.define_own_property(i, attrs)
        if constructor:
            attrs['value'] = constructor
            prototype.define_own_property('constructor', attrs)
            



PyJs.undefined = undefined
PyJs.Js = staticmethod(Js)

from prototypes import jsfunction, jsobject, jsnumber, jsstring, jsboolean, jsarray, jsregexp, jserror


#Object proto
fill_prototype(ObjectPrototype, jsobject.ObjectPrototype, default_attrs)
#Define __proto__ accessor (this cant be done by fill_prototype since)
@Js
def __proto__():
    return this.prototype if this.prototype is not None else null
getter = __proto__
@Js
def __proto__(val):
    print 'Setting proto'
    print val
    if val.is_object():
        print 'Yes its an object'
        this.prototype = val
setter =  __proto__
ObjectPrototype.define_own_property('__proto__', {'set': setter,
                                                  'get': getter,
                                                  'enumerable': False,
                                                  'configurable':True})


#Function proto
fill_prototype(FunctionPrototype, jsfunction.FunctionPrototype, default_attrs)
#Number proto
fill_prototype(NumberPrototype, jsnumber.NumberPrototype, default_attrs)
#String proto
fill_prototype(StringPrototype, jsstring.StringPrototype, default_attrs)
#Boolean proto
fill_prototype(BooleanPrototype, jsboolean.BooleanPrototype, default_attrs)
#Array proto
fill_prototype(ArrayPrototype, jsarray.ArrayPrototype, default_attrs)
#Error proto
fill_prototype(ErrorPrototype, jserror.ErrorPrototype, default_attrs)
#RegExp proto
fill_prototype(RegExpPrototype, jsregexp.RegExpPrototype, default_attrs)
# add exec to regexpfunction (cant add it automatically because of its name :(
default_attrs['value'] = jsregexp.Exec
RegExpPrototype.define_own_property('exec', default_attrs)

#########################################################################
# Constructors

# String
@Js
def String():
    if not len(arguments):
        return Js('')
    return arguments[0].to_string()

@Js
def string_constructor():
    temp = PyJsObject(prototype=StringPrototype)
    temp.Class = 'String'
    if not len(arguments):
        temp.value = ''
    else:
        temp.value = arguments[0].to_string().value
    return temp

String.create = string_constructor

# RegExp

@Js
def RegExp(pattern, flags):
    if pattern.Class=='RegExp':
        if flags.is_undefined():
            raise  MakeError('TypeError', 'Cannot supply flags when constructing one RegExp from another')
        # copy the pattern
        temp  = copy(pattern)
        temp.own = copy(pattern.own)
        return temp
    #pattern is not a regexp
    if pattern.is_undefined():
        pattern = ''
    else:
        pattern = pattern.to_string().value
    flags = flags.to_string().value if not flags.is_undefined() else ''
    pattern  = '/%s/'%(pattern if pattern else '(?:)') + flags
    return JsRegExp(pattern)

RegExp.create = RegExp
PyJs.RegExp = RegExp

# Number

@Js
def Number():
    if len(arguments):
        return arguments[0].to_number()
    else:
        return Js(0)

@Js
def number_constructor():
    temp = PyJsObject(prototype=NumberPrototype)
    temp.Class = 'Number'
    if len(arguments):
        temp.value = arguments[0].to_number().value
    else:
        temp.value = 0
    return temp

Number.create = number_constructor

# Boolean

@Js
def Boolean(value):
    return value.to_boolean()
@Js
def boolean_constructor(value):
    temp = PyJsObject(prototype=BooleanPrototype)
    temp.Class = 'Boolean'
    temp.value = value.to_boolean().value
    return temp

Boolean.create = boolean_constructor

##############################################################################

def appengine(code):
    try:
        return translator.translate_js(code)
    except:
        return traceback.format_exc()
        
        
        
builtins = ('true','false','null','undefined','Infinity',
            'NaN')

scope = dict(zip(builtins, [eval(e) for e in builtins]))

JS_BUILTINS = {k:v for k,v in scope.iteritems()}


if __name__=='__main__':
    print ObjectPrototype.get('toString').callprop('call')
    print FunctionPrototype.own
    a=  null-Js(49404)
    x = a.put('ser', Js('der'))
    print Js(0) or Js('p') and Js(4.0000000000050000001)
    FunctionPrototype.put('Chuj', Js(409))
    for e in FunctionPrototype:
        print 'Obk', e.get('__proto__').get('__proto__').get('__proto__'), e
    import code
    s = Js(4)
    b = Js(6)
    s2 = Js(4)
    o =  ObjectPrototype
    o.put('x', Js(100))
    var = Scope(scope)
    e = code.InteractiveConsole(globals())
    #e.raw_input = interactor
    e.interact()
