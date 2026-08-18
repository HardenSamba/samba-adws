import ast

DEF_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPE_TYPES = DEF_TYPES + (ast.ClassDef,)
BLOCK_TYPES = (
    ast.If, ast.For, ast.While, ast.With, ast.Try,
    ast.AsyncFor, ast.AsyncWith,
)
