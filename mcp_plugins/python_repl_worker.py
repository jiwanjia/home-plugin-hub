"""Child-process protocol for one reply-scoped Python namespace."""

import ast
import contextlib
import io
import json
import sys
import traceback


def execute_code(code, namespace):
    """Execute statements and evaluate a final expression like a REPL."""
    module = ast.parse(code, mode="exec")
    final_expression = None
    if module.body and isinstance(module.body[-1], ast.Expr):
        final_expression = ast.Expression(module.body.pop().value)

    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        if module.body:
            exec(compile(module, "<run_python>", "exec"), namespace, namespace)
        value = None
        if final_expression is not None:
            value = eval(
                compile(final_expression, "<run_python>", "eval"),
                namespace,
                namespace,
            )

    output = stdout.getvalue() + stderr.getvalue()
    if final_expression is not None and value is not None:
        output += repr(value)
        if not output.endswith("\n"):
            output += "\n"
    return output


def main():
    namespace = {"__name__": "__run_python__"}
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            output = execute_code(request.get("code", ""), namespace)
            response = {"id": request.get("id"), "ok": True, "output": output}
        except BaseException as exc:
            response = {
                "id": request.get("id") if isinstance(request, dict) else None,
                "ok": False,
                "error": "".join(
                    traceback.format_exception_only(type(exc), exc)
                ).strip(),
            }
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
