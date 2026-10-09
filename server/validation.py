"""Small strict JSON Schema validator for the shipped schemas; no dependencies."""
import re

class CaseError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)

def check(value, schema, path='$'):
    types = {'object':dict, 'array':list, 'string':str, 'integer':int, 'number':(int,float), 'boolean':bool}
    t = schema.get('type')
    if t and (not isinstance(value, types[t]) or t in ('integer','number') and isinstance(value,bool)):
        raise CaseError('SCHEMA_ERROR', f'{path}: expected {t}')
    if 'enum' in schema and value not in schema['enum']:
        raise CaseError('SCHEMA_ERROR', f'{path}: invalid enum')
    if isinstance(value, dict):
        for key in schema.get('required',[]):
            if key not in value: raise CaseError('SCHEMA_ERROR',f'{path}.{key}: required')
        props = schema.get('properties',{})
        for key, val in value.items():
            if key in props: check(val, props[key], f'{path}.{key}')
            elif schema.get('additionalProperties') is False:
                raise CaseError('SCHEMA_ERROR',f'{path}.{key}: unknown field')
    if isinstance(value,list):
        if len(value)<schema.get('minItems',0): raise CaseError('SCHEMA_ERROR',f'{path}: too few items')
        if len(value)>schema.get('maxItems',100000): raise CaseError('SCHEMA_ERROR',f'{path}: too many items')
        for i,v in enumerate(value): check(v,schema.get('items',{}),f'{path}[{i}]')
    if isinstance(value,str):
        if len(value)<schema.get('minLength',0) or len(value)>schema.get('maxLength',1000000):
            raise CaseError('SCHEMA_ERROR',f'{path}: invalid length')
        if 'pattern' in schema and not re.search(schema['pattern'],value):
            raise CaseError('SCHEMA_ERROR',f'{path}: invalid format')
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        if value<schema.get('minimum',float('-inf')) or value>schema.get('maximum',float('inf')):
            raise CaseError('SCHEMA_ERROR',f'{path}: out of range')
