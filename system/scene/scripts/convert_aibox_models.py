#!/usr/bin/env python3
# SPDX-License-Identifier: MulanPSL-2.0
"""Convert Scene's DualMap perception models for the AIBOX RKNPU3 (RK1828).

Three graphs, one per heavy model DualMap runs per keyframe:

- ``yoloworld``    YOLO-World detector with a *fixed* vocabulary baked in at
                   export time (its CLIP text branch runs once on the PC).
                   Input uint8 NHWC [1,640,640,3], output [1,4+nc,8400]
                   pre-NMS; letterbox/NMS post-processing stays on CPU.
- ``mobilesam``    MobileSAM's TinyViT image encoder. The deployed bundle also
                   uses the fixed-shape decoder described in
                   ``AIBOX_MODEL_PORTING.md``.
- ``mobileclip``   MobileCLIP-S2 image encoder for per-crop embeddings.

Two stages because the toolchains live in different virtualenvs:

    # stage 1 - export ONNX (+ .npt reference outputs); ML env (torch CUDA,
    # ultralytics, open_clip, mobileclip)
    convert_aibox_models.py export  <model> --weights-dir D --out-dir D \
        --classes-file F [--yoloworld-weights yolov8s-worldv2.pt] [--image IMG]

    # stage 2 - compile to .rknn(+.weight) and validate in the PC simulator;
    # RKNN3 Toolkit env (version must match the board's rknn3_toolkit_lite)
    convert_aibox_models.py build   <model> --onnx F --out-dir D \
        [--dataset F] [--no-quant] [--optimization-level N] [--image IMG]

Run ``export`` with the ML venv python and ``build`` with the toolkit venv
python. The board-side smoke test is ``test_aibox_rknn_lite.py``.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys


def _load_classes(path: str) -> list[str]:
    with open(path) as fh:
        names = [ln.strip() for ln in fh if ln.strip()]
    if not names:
        raise SystemExit(f"empty classes file: {path}")
    return names


# ── stage 1: ONNX export ────────────────────────────────────────────────────


def cmd_export(args: argparse.Namespace) -> None:
    os.makedirs(args.out_dir, exist_ok=True)
    if args.model == "yoloworld":
        _export_yoloworld(args)
    elif args.model == "mobilesam":
        _export_mobilesam_encoder(args)
    elif args.model == "mobileclip":
        _export_mobileclip_visual(args)
    elif args.model == "clip_image":
        _export_clip_visual(args)
    elif args.model == "clip_text":
        _export_clip_text(args)
    else:
        raise SystemExit(f"unknown model: {args.model}")


def _check_image(args: argparse.Namespace) -> str:
    import cv2

    if not args.image or not os.path.isfile(args.image):
        raise SystemExit(f"--image {args.image!r} is required for the reference dump")
    return cv2.imread(args.image)


def _save_ref(out_dir: str, name: str, **arrays) -> None:
    import numpy as np

    path = os.path.join(out_dir, name)
    np.savez(path, **arrays)
    print(f"[export] reference tensors -> {path}.npz")


def _patch_image_pooling_attn() -> None:
    """ONNX cannot trace AdaptiveMaxPool2d to (k,k) when the feature size is
    not divisible by k (YOLO-World's RepVL-PAN pools 80/40/20 -> 3x3). At the
    static export size the cells are known, so slice-and-reduce-max gives the
    same result with exportable ops."""
    import torch

    from ultralytics.nn.modules.block import ImagePoolingAttn

    orig_forward = ImagePoolingAttn.forward

    def pool_fixed(x: "torch.Tensor", k: int) -> "torch.Tensor":
        h, w = int(x.shape[-2]), int(x.shape[-1])
        cells = []
        for i in range(k):
            h0, h1 = (i * h) // k, -((-(i + 1) * h) // k)
            for j in range(k):
                w0, w1 = (j * w) // k, -((-(j + 1) * w) // k)
                cells.append(x[..., h0:h1, w0:w1].amax(dim=(-2, -1)))
        out = torch.stack(cells, dim=-1)
        return out.view(*x.shape[:2], k, k)

    def forward(self, x, text):
        bs = x[0].shape[0]
        assert len(x) == self.nf
        num_patches = self.k**2
        x = [pool_fixed(proj(feat), self.k).view(bs, -1, num_patches)
             for feat, proj in zip(x, self.projections)]
        x = torch.cat(x, dim=-1).transpose(1, 2)
        q = self.query(text)
        k = self.key(x)
        v = self.value(x)

        # q = q.reshape(1, text.shape[1], self.nh, self.hc).repeat(bs, 1, 1, 1)
        q = q.reshape(bs, -1, self.nh, self.hc)
        k = k.reshape(bs, -1, self.nh, self.hc)
        v = v.reshape(bs, -1, self.nh, self.hc)

        aw = torch.einsum("bnmc,bkmc->bmnk", q, k)
        aw = aw / (self.hc**0.5)
        aw = torch.nn.functional.softmax(aw, dim=-1)

        x = torch.einsum("bmnk,bkmc->bnmc", aw, v)
        x = self.proj(x.reshape(bs, -1, self.ec))
        return x * self.scale + text

    # Same math as the original forward; keep a reference for sanity checks.
    ImagePoolingAttn.forward = forward
    ImagePoolingAttn._orig_forward = orig_forward


def _export_yoloworld(args: argparse.Namespace) -> None:
    """set_classes() bakes the vocabulary into the graph; export then emits a
    single-input, fixed-shape ONNX whose head output is [1,4+nc,8400]."""
    from ultralytics import YOLO

    _patch_image_pooling_attn()
    classes = _load_classes(args.classes_file)
    weight = args.yoloworld_weights or os.path.join(
        args.weights_dir, "yolov8s-worldv2.pt"
    )
    if not os.path.isfile(weight):
        raise SystemExit(f"YOLO-World checkpoint not found: {weight}")
    model = YOLO(weight)
    model.set_classes(classes)
    onnx_path = model.export(
        format="onnx", imgsz=args.imgsz, opset=args.opset, dynamic=False,
        simplify=False, half=False, nms=False,
    )
    output_path = os.path.join(args.out_dir, "yoloworld.onnx")
    if os.path.abspath(onnx_path) != os.path.abspath(output_path):
        shutil.copy2(onnx_path, output_path)
    onnx_path = output_path
    sidecar = {
        "model": "yoloworld", "classes": classes, "imgsz": args.imgsz,
        "weights": os.path.abspath(weight), "opset": args.opset,
        "output": "pre_nms [1,4+nc,8400]",
    }
    with open(os.path.join(args.out_dir, "yoloworld.json"), "w") as fh:
        json.dump(sidecar, fh, indent=2)

    img = _check_image(args)
    ref = model.predict(img[:, :, ::-1], conf=0.2, verbose=False)  # BGR->RGB
    r = ref[0]
    _save_ref(args.out_dir, "yoloworld_ref",
              xyxy=r.boxes.xyxy.cpu().numpy(), conf=r.boxes.conf.cpu().numpy(),
              cls=r.boxes.cls.cpu().numpy().astype(int))
    print(f"[export] {onnx_path}: {len(classes)} classes baked, "
          f"{len(r.boxes)} reference boxes from {args.image}")


def _export_mobilesam_encoder(args: argparse.Namespace) -> None:
    """Export ``image_encoder``; the fixed-shape decoder is built separately."""
    import torch
    from ultralytics import SAM

    weight = os.path.join(args.weights_dir, "mobile_sam.pt")
    sam = SAM(weight)
    encoder = sam.model.image_encoder.eval()
    dummy = torch.zeros(1, 3, args.imgsz, args.imgsz)
    out_path = os.path.join(args.out_dir, "mobilesam_encoder.onnx")
    torch.onnx.export(
        encoder, dummy, out_path, opset_version=args.opset,
        input_names=["images"], output_names=["image_embeddings"],
        dynamic_axes=None,
    )

    img = _check_image(args)
    ref = _sam_reference(sam, img)
    _save_ref(args.out_dir, "mobilesam_ref", **ref)
    print(f"[export] {out_path} (encoder only, {args.imgsz}x{args.imgsz})")


def _sam_reference(sam, img_bgr):
    """The exact preprocessing ultralytics' SAM predictor applies, plus the
    encoder output, so the board test can compare end to end."""
    import numpy as np
    import torch

    from ultralytics.data.augment import LetterBox

    letterbox = LetterBox(1024, auto=False, stride=32)
    im = letterbox(image=img_bgr)
    im = im.transpose(2, 0, 1)[::-1]  # HWC BGR -> CHW RGB
    im = np.ascontiguousarray(im)
    im = torch.from_numpy(im).float()
    mean = torch.tensor([123.675, 116.28, 103.53]).view(-1, 1, 1)
    std = torch.tensor([58.395, 57.12, 57.375]).view(-1, 1, 1)
    im = (im - mean) / std
    with torch.no_grad():
        emb = sam.model.image_encoder(im[None])
    return {"image": img_bgr, "preprocessed": im.numpy(), "embedding": emb.numpy()}


def _export_mobileclip_visual(args: argparse.Namespace) -> None:
    """MobileCLIP-S2 image tower; crops are resized to 256 square outside the
    graph (batch=1 per crop; the NPU needs a static batch)."""
    import torch

    import mobileclip  # noqa: F401  (registers the arch with open_clip)
    import open_clip

    weight = os.path.join(args.weights_dir, "mobileclip_s2_datacompdr.bin")
    model, _, preprocess = open_clip.create_model_and_transforms(
        "MobileCLIP-S2", pretrained=weight)
    model = model.eval()
    from mobileclip.modules.common.mobileone import reparameterize_model

    visual = reparameterize_model(model.visual).eval()
    size = getattr(visual, "image_size", None)
    if isinstance(size, (list, tuple)):
        size = size[0]
    if size is None:
        size = getattr(model.visual, "image_size", 256)
    dummy = torch.zeros(1, 3, size, size)
    out_path = os.path.join(args.out_dir, "mobileclip_image.onnx")
    torch.onnx.export(
        visual, dummy, out_path, opset_version=args.opset,
        input_names=["images"], output_names=["image_features"],
        dynamic_axes=None,
    )

    import cv2
    import numpy as np

    if args.image and os.path.isfile(args.image):
        img = cv2.imread(args.image)[:, :, ::-1]  # RGB
        x = torch.from_numpy(img.copy()).permute(2, 0, 1).float() / 255.0
        x = torch.nn.functional.interpolate(x[None], size=(size, size),
                                            mode="bicubic", align_corners=False)
        mean = torch.tensor([0.48145466, 0.4578275, 0.40821073]).view(3, 1, 1)
        std = torch.tensor([0.26862954, 0.44899216, 0.44970418]).view(3, 1, 1)
        norm = (x - mean) / std
        with torch.no_grad():
            feat = visual(norm)
            feat = feat / feat.norm(dim=-1, keepdim=True)
        _save_ref(args.out_dir, "mobileclip_ref", image=img,
                  preprocessed=norm[0].numpy(), feature=feat[0].numpy())
    with open(os.path.join(args.out_dir, "mobileclip.json"), "w") as fh:
        json.dump({"model": "MobileCLIP-S2", "image_size": size,
                   "input": f"[1,3,{size},{size}] fp32, CLIP-normalized"}, fh, indent=2)
    print(f"[export] {out_path} ({size}x{size})")


def _export_clip_visual(args: argparse.Namespace) -> None:
    """OpenAI CLIP ViT-B/32 image tower. MobileCLIP-S2's FastViT reaches
    absmax ~1e5 mid-graph (over fp16) and decorrelates at w8a8, so the NPU
    path standardises on the ViT-B/32 space that YOLO-World's text branch
    already uses. Input 224x224, CLIP normalization, output [1,512]."""
    import numpy as np
    import torch
    import clip

    model, _ = clip.load("ViT-B/32", device="cpu")
    visual = model.visual.eval()
    dummy = torch.zeros(1, 3, 224, 224)
    out_path = os.path.join(args.out_dir, "clip_image.onnx")
    torch.onnx.export(visual, dummy, out_path, opset_version=args.opset,
                      input_names=["images"], output_names=["image_features"],
                      dynamic_axes=None)
    onnx_full = out_path.replace(".onnx", "_full.onnx")
    import onnx

    m = onnx.load(out_path)
    onnx.save_model(m, onnx_full, save_as_external_data=False)
    os.replace(onnx_full, out_path)
    if os.path.exists(out_path + ".data"):
        os.remove(out_path + ".data")

    if args.image and os.path.isfile(args.image):
        import cv2

        img = cv2.imread(args.image)[:, :, ::-1]
        x = torch.from_numpy(img.copy()).permute(2, 0, 1).float() / 255.0
        x = torch.nn.functional.interpolate(x[None], size=(224, 224), mode="bicubic",
                                            align_corners=False)
        mean = torch.tensor([0.48145466, 0.4578275, 0.40821073]).view(3, 1, 1)
        std = torch.tensor([0.26862954, 0.44899216, 0.44970418]).view(3, 1, 1)
        norm = (x - mean) / std
        with torch.no_grad():
            feat = visual(norm)
            feat = feat / feat.norm(dim=-1, keepdim=True)
        _save_ref(args.out_dir, "clip_image_ref", image=img,
                  preprocessed=norm[0].numpy(), feature=feat[0].numpy())
    with open(os.path.join(args.out_dir, "clip_image.json"), "w") as fh:
        json.dump({"model": "clip/ViT-B/32 visual", "image_size": 224,
                   "input": "[1,3,224,224] fp32, CLIP-normalized"}, fh, indent=2)
    print(f"[export] {out_path} (224x224)")


def _export_clip_text(args: argparse.Namespace) -> None:
    """OpenAI CLIP ViT-B/32 text tower: token ids [1,77] (int) -> [1,512].
    Matches the embedding space of the zoo YOLO-World text input."""
    import numpy as np
    import torch
    import clip

    model, _ = clip.load("ViT-B/32", device="cpu")
    text_encoder = model.eval()

    class _TextTower(torch.nn.Module):
        def forward(self, tokens: "torch.Tensor") -> "torch.Tensor":
            return text_encoder.encode_text(tokens)

    dummy = torch.randint(0, 49000, (1, 77))
    out_path = os.path.join(args.out_dir, "clip_text.onnx")
    torch.onnx.export(_TextTower().eval(), (dummy,), out_path, opset_version=args.opset,
                      input_names=["tokens"], output_names=["text_features"],
                      dynamic_axes=None)
    import onnx
    from onnx import helper as _h

    m = onnx.load(out_path)
    # The RKNN3 toolkit crashes on int64 graph inputs; feed float token ids
    # and cast back to int inside the graph.
    old = m.graph.input[0]
    old_name = old.name
    new = _h.make_tensor_value_info("tokens", onnx.TensorProto.FLOAT, [1, 77])
    cast_out = "tokens_int64_rknn"
    cast = _h.make_node("Cast", [ "tokens" ], [cast_out], name="tokens_cast",
                        to=onnx.TensorProto.INT64)
    m.graph.node.insert(0, cast)
    for node in list(m.graph.node)[1:]:  # skip the cast itself: it consumes the new input
        for i, name in enumerate(node.input):
            if name == old_name:
                node.input[i] = cast_out
    m.graph.input.remove(old)
    m.graph.input.insert(0, new)
    onnx.save_model(m, out_path.replace(".onnx", "_full.onnx"),
                    save_as_external_data=False)
    os.replace(out_path.replace(".onnx", "_full.onnx"), out_path)
    if os.path.exists(out_path + ".data"):
        os.remove(out_path + ".data")

    toks = clip.tokenize(["a chair", "a photo of a desk"])
    with torch.no_grad():
        feat = model.encode_text(toks)
        feat = feat / feat.norm(dim=-1, keepdim=True)
    _save_ref(args.out_dir, "clip_text_ref", tokens=toks.numpy(),
              feature=feat.numpy())
    print(f"[export] {out_path} (77 tokens -> 512)")


# ── stage 2: RKNN build + simulator validation ──────────────────────────────


def cmd_build(args: argparse.Namespace) -> None:
    from rknn.api import RKNN

    os.makedirs(args.out_dir, exist_ok=True)
    quant = not args.no_quant
    if quant and not (args.dataset and os.path.isfile(args.dataset)):
        raise SystemExit("--dataset (a txt of calibration image paths) is required "
                         "for quantized builds, or pass --no-quant")
    rknn = RKNN(verbose=args.verbose)

    cfg = dict(target_platform="rk1820", optimization_level=args.optimization_level)
    if args.model == "yoloworld":
        # uint8 in, mean/std absorbed by the graph (ultralytics normalization)
        cfg.update(
            mean_values=[[0, 0, 0]], std_values=[[255, 255, 255]],
            input_attrs={"images": {"dtype": "uint8", "layout": "NHWC"}},
            disable_rules=["fuse_conv_rs_exmatmul_to_conv"],
        )
        if quant:
            cfg.update(
                quantized_dtype="w8a8", quantized_algorithm="normal",
                quantized_method="channel",
            )
    elif args.model == "mobilesam":
        cfg.update(
            mean_values=[[123.675, 116.28, 103.53]], std_values=[[58.395, 57.12, 57.375]],
            input_attrs={"images": {"dtype": "uint8", "layout": "NHWC"}},
        )
    elif args.model == "mobileclip":
        cfg.update(
            mean_values=[[(0.48145466 * 255), (0.4578275 * 255), (0.40821073 * 255)]],
            std_values=[[(0.26862954 * 255), (0.44899216 * 255), (0.44970418 * 255)]],
            input_attrs={"images": {"dtype": "uint8", "layout": "NHWC"}},
        )
    else:
        raise SystemExit(f"unknown model: {args.model}")

    print("--> config")
    if rknn.config(**cfg) != 0:
        raise SystemExit("config failed")
    print("--> load_onnx")
    if rknn.load_onnx(model=args.onnx) != 0:
        raise SystemExit("load_onnx failed")
    print("--> build")
    if rknn.build(do_quantization=quant, dataset=args.dataset) != 0:
        raise SystemExit("build failed")
    rknn_path = os.path.join(args.out_dir, f"{args.model}.rknn")
    print("--> export_rknn")
    if rknn.export_rknn(rknn_path) != 0:
        raise SystemExit("export_rknn failed")
    print(f"[build] {rknn_path} (quant={quant}, opt_level={args.optimization_level})")

    if args.image:
        _sim_check(rknn, args)


def _sim_check(rknn, args: argparse.Namespace) -> None:
    """Run one real image through the PC simulator and stash outputs for the
    board-side comparison (the simulator approximates, not equals, the NPU)."""
    import cv2

    if rknn.init_runtime() != 0:
        raise SystemExit("simulator init_runtime failed")
    img = cv2.imread(args.image)
    if img is None:
        raise SystemExit(f"cannot read {args.image}")
    x = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    import numpy as np

    h = w = 640 if args.model == "yoloworld" else (1024 if args.model == "mobilesam" else 256)
    x = cv2.resize(x, (w, h))
    outputs = rknn.inference(inputs=[np.expand_dims(x, 0)], data_format=["nhwc"])
    out = os.path.join(args.out_dir, f"{args.model}_sim.npz")
    np.savez(out, **{f"out{i}": o for i, o in enumerate(outputs)})
    for i, o in enumerate(outputs):
        print(f"[sim] out{i}: shape={o.shape} dtype={o.dtype} "
              f"min={np.nanmin(o):.4g} max={np.nanmax(o):.4g} nonzero={np.count_nonzero(o)}")
    print(f"[sim] outputs -> {out}")


def cmd_deploy(args: argparse.Namespace) -> None:
    """Assemble the DualMap `model/npu` directory from build artifacts."""
    import shutil

    os.makedirs(args.out_dir, exist_ok=True)
    classes = _load_classes(args.classes_file)
    renames = {
        "yoloworld": ("yolo_world_v2s_fp16.rknn", "yoloworld.rknn"),
        "yoloworld_text": ("scene40_text_outp.npy", "yoloworld_text.npy"),
        "mobilesam": ("mobilesam.rknn", "mobilesam.rknn"),
        "clip_image": ("clip_image.rknn", "clip_image.rknn"),
    }
    for key, (src_name, dst_name) in renames.items():
        srcs = [(src_name, dst_name)]
        if src_name.endswith(".rknn"):
            srcs.append((src_name[: -len(".rknn")] + ".weight",
                         dst_name[: -len(".rknn")] + ".weight"))
        for src_name, dst_name in srcs:
            src = os.path.join(args.rknn_dir, src_name)
            if not os.path.isfile(src):
                raise SystemExit(f"missing artifact: {src}")
            shutil.copy2(src, os.path.join(args.out_dir, dst_name))
    with open(os.path.join(args.out_dir, "npu_meta.json"), "w") as fh:
        json.dump({"classes": classes, "graphs": {"yoloworld": "yolo_world_v2s fp16",
                                                  "mobilesam": "encoder fp16",
                                                  "clip_image": "clip ViT-B/32 visual fp16"},
                   "text": "openai/clip-vit-base-patch32, L2-normalized, padded to 80"},
                  fh, indent=2)
    print(f"[deploy] {args.out_dir}: {len(classes)} classes")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, *, with_onnx, models):
        p.add_argument("model", choices=models)
        p.add_argument("--out-dir", required=True)
        if with_onnx:
            p.add_argument("--onnx", required=True)
        p.add_argument("--image", help="real image for reference/simulator dumps")
        p.add_argument("--verbose", action="store_true")

    p = sub.add_parser("export", help="ONNX export + reference tensors")
    common(p, with_onnx=False,
           models=["yoloworld", "mobilesam", "mobileclip", "clip_image", "clip_text"])
    p.add_argument("--weights-dir", required=True)
    p.add_argument(
        "--yoloworld-weights",
        help="YOLO-World checkpoint; defaults to <weights-dir>/yolov8s-worldv2.pt",
    )
    p.add_argument("--classes-file", help="vocabulary, one name per line (yoloworld)")
    p.add_argument("--imgsz", type=int, default=640, help="yoloworld/mobilesam input size")
    p.add_argument("--opset", type=int, default=12)

    # build implements yoloworld/mobilesam/mobileclip only; the CLIP graphs
    # come from the zoo pipeline (fetch_zoo_aibox_models.py).
    p = sub.add_parser("build", help="compile ONNX -> .rknn, optional sim check")
    common(p, with_onnx=True, models=["yoloworld", "mobilesam", "mobileclip"])
    p.add_argument("--dataset", help="calibration image list txt (quantized builds)")
    p.add_argument("--no-quant", action="store_true", help="fp build (no int8)")
    p.add_argument("--optimization-level", type=int, default=0)

    p = sub.add_parser("deploy", help="assemble DualMap model/npu from artifacts")
    p.add_argument("--rknn-dir", required=True)
    p.add_argument("--classes-file", required=True)
    p.add_argument("--out-dir", required=True)

    args = ap.parse_args()
    if args.cmd == "export":
        cmd_export(args)
    elif args.cmd == "deploy":
        cmd_deploy(args)
    else:
        cmd_build(args)


if __name__ == "__main__":
    main()
