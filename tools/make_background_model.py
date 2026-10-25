"""Make Docly's fixed-size background model from the MODNet ONNX export.

Developer tool, not part of the app. Needs: pip install onnx onnxsim

    python tools/make_background_model.py model.onnx

Download model.onnx from https://huggingface.co/Xenova/modnet (folder onnx/).
Writes assets/models/modnet_512.onnx.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SIZE = 512
OUT = Path(__file__).resolve().parent.parent / "assets" / "models" / "modnet_512.onnx"


def main(source: str) -> int:
    import onnx
    from onnxsim import simplify

    model = onnx.load(source)
    for dim, value in zip(model.graph.input[0].type.tensor_type.shape.dim, (1, 3, SIZE, SIZE), strict=True):
        dim.ClearField("dim_param")
        dim.dim_value = value
    simplified, ok = simplify(model, overwrite_input_shapes={"input": [1, 3, SIZE, SIZE]})
    if not ok:
        print("onnx-simplifier could not verify the model")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(simplified, OUT)
    print(f"Wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    print("SHA-256", hashlib.sha256(OUT.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
