"""HTTP over clear(). Transport only -- no market arithmetic lives here.

    POST /clear  {config, slack, limits}  ->  a priced, settled day

The engine does not change to suit this layer. src/api/ imports from
src/model/ and src/ingest/ and is imported by neither.
"""
