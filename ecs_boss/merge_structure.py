"""
Intellegently merge complex structures

"""
import collections


def merge_environment(d, u):
    """
    Intellegently merge the list of environment variables
    """
    d_index = dict([(x['name'], x['value']) for x in d])

    for item in u:
        d_index[item['name']] = item['value']

    return [{'name': k, 'value': v} for k, v in d_index.items()]


def merge_containerDefinitions(d, u):  # NOQA
    """
    Intellegently merge the list of containerDefinitions
    """
    # Create a index of name -> definition
    d_index = dict([(x['name'], x) for x in d])

    # iterate through each definition
    for item in u:
        name = item['name']
        d_index[name] = recursive_update(d_index.get(name, {}), item)

    return d_index.values()


def recursive_update(d, u):
    """
    Recursively update a structure

    Looks for a `merge_<keyname>` function in globals() to handle the merging.
    Failing that, it does a simple update.
    """
    for k, v in u.iteritems():
        func_name = "merge_%s" % k
        if func_name in globals():
            d[k] = globals()[func_name](d.get(k, {}), v)
        elif isinstance(v, collections.Mapping):
            r = recursive_update(d.get(k, {}), v)
            d[k] = r
        else:
            d[k] = u[k]
    return d
