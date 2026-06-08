"""Run final regression with rating=other to verify the rest of the API chain.

This is a companion script for qa_final_regression.py. The strict script must pass
for final acceptance; this one proves that the remaining backend paths work when
bypassing the known rating=user_feedback enum blocker.
"""
from pathlib import Path

source = Path(__file__).with_name("qa_final_regression.py")
text = source.read_text(encoding="utf-8")
text = text.replace('"rating": "user_feedback"', '"rating": "other"')
text = text.replace("rating=user_feedback response:", "rating=other response:")
text = text.replace("rating=user_feedback must not return 400/validation error", "rating=other must not return 400/validation error")
code = compile(text, str(source), "exec")
exec(code, {"__name__": "__main__", "__file__": str(source)})
