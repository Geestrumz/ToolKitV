#!/usr/bin/env python3
"""
ytd_downsize.py - Downsize GTA V .ytd texture dictionary files

Requires:
  - Windows (texconv.exe is Windows-only)
  - .NET 6.0 or newer (https://dotnet.microsoft.com/en-us/download)
  - pythonnet  (pip install pythonnet)
  - CodeWalker.Core.dll  (already shipped in Application/Dependencies/)
  - texconv.exe           (already shipped in Application/Dependencies/)

Quick start:
  pip install pythonnet
  python ytd_downsize.py --input "C:/path/to/ytd/files"

Options:
  --input/-i          Directory containing .ytd files (searched recursively)
  --backup/-b         Directory to copy originals into before modifying
  --min-size          Minimum combined width+height to optimize  [default: 8192]
  --downsize          Halve texture dimensions  [default: on]
  --no-downsize       Disable dimension halving
  --format-optimize   Force all textures to BC1/BC3 regardless of source format
  --only-oversized    Skip files whose physical (RSC) size is <= 16 MB
  --dry-run           Print what would change without writing anything
  --texconv           Path to texconv.exe  [default: auto-detect]
  --dll               Path to CodeWalker.Core.dll  [default: auto-detect]
  --verbose/-v        Extra logging
"""

import argparse
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _find_sibling(*candidates: str) -> str | None:
    """Search common locations relative to this script for a file."""
    script_dir = Path(__file__).parent
    search = [
        script_dir,
        script_dir / "Application" / "Dependencies",
        script_dir / "Dependencies",
    ]
    for rel in candidates:
        for base in search:
            p = base / rel
            if p.exists():
                return str(p)
    return None


def _flag_to_size(flag: int) -> float:
    """Convert a GTA V RSC size-flag to bytes (mirrors C# FlagToSize)."""
    return (
        ((flag >> 17) & 0x7F)
        + (((flag >> 11) & 0x3F) << 1)
        + (((flag >> 7) & 0xF) << 2)
        + (((flag >> 5) & 0x3) << 3)
        + (((flag >> 4) & 0x1) << 4)
    ) * (0x2000 << (flag & 0xF))


def get_rsc_sizes(path: str) -> tuple[float, float]:
    """
    Read the RSC7 header and return (virtual_mb, physical_mb).
    Returns (0, 0) if the file is not a valid RSC7.
    """
    try:
        with open(path, "rb") as f:
            header = f.read(16)
        if len(header) < 16:
            return 0.0, 0.0
        magic = header[:4]
        if magic != b"RSC7":
            return 0.0, 0.0
        # skip 4-byte version field
        v_flag = struct.unpack_from("<I", header, 8)[0]
        p_flag = struct.unpack_from("<I", header, 12)[0]
        return _flag_to_size(v_flag) / 1024 / 1024, _flag_to_size(p_flag) / 1024 / 1024
    except OSError:
        return 0.0, 0.0


# ---------------------------------------------------------------------------
# texture-format helpers (mirrors TextureOptimization.cs switch blocks)
# ---------------------------------------------------------------------------

# Map CodeWalker TextureFormat enum names → texconv format string
_FORMAT_MAP: dict[str, str] = {
    "D3DFMT_DXT1":   "BC1_UNORM",
    "D3DFMT_DXT3":   "BC2_UNORM",
    "D3DFMT_DXT5":   "BC3_UNORM",
    "D3DFMT_ATI1":   "BC4_UNORM",
    "D3DFMT_ATI2":   "BC5_UNORM",
    "D3DFMT_BC7":    "BC5_UNORM",
    # uncompressed
    "D3DFMT_A1R5G5B5": "B5G5R5A1_UNORM",
    "D3DFMT_A8":       "A8_UNORM",
    "D3DFMT_A8B8G8R8": "R8G8B8A8_UNORM",
    "D3DFMT_L8":       "R8_UNORM",
    "D3DFMT_A8R8G8B8": "B8G8R8A8_UNORM",
}

_ALPHA_FORMATS = {"D3DFMT_DXT5", "D3DFMT_A1R5G5B5", "D3DFMT_A8B8G8R8", "D3DFMT_A8R8G8B8"}


def _texconv_format(fmt_name: str, format_optimize: bool) -> str | None:
    if format_optimize:
        return "BC3_UNORM" if fmt_name in _ALPHA_FORMATS else "BC1_UNORM"
    return _FORMAT_MAP.get(fmt_name)


# ---------------------------------------------------------------------------
# CodeWalker interop via pythonnet
# ---------------------------------------------------------------------------

def _load_codewalker(dll_path: str):
    """
    Import CodeWalker.Core.dll using pythonnet and return the module-level
    namespace that exposes YtdFile, DDSIO, etc.
    Raises ImportError with a helpful message on failure.
    """
    try:
        import clr  # noqa: F401  (pythonnet)
    except ModuleNotFoundError:
        raise ImportError(
            "pythonnet is not installed.\n"
            "Install it with:  pip install pythonnet\n"
            "Then retry."
        ) from None

    clr.AddReference(dll_path)  # type: ignore[attr-defined]

    # These imports work once the assembly is loaded
    from CodeWalker.GameFiles import (  # type: ignore[import]
        YtdFile,
        RpfFile,
        RpfBinaryFileEntry,
        JenkHash,
        ResourceBuilder,
        TextureFormat,
    )
    from CodeWalker.Utils import DDSIO  # type: ignore[import]

    return {
        "YtdFile": YtdFile,
        "RpfFile": RpfFile,
        "RpfBinaryFileEntry": RpfBinaryFileEntry,
        "JenkHash": JenkHash,
        "ResourceBuilder": ResourceBuilder,
        "TextureFormat": TextureFormat,
        "DDSIO": DDSIO,
    }


def _create_file_entry(cw, name: str, path: str, data: bytearray):
    """Mirrors CreateFileEntry() in TextureOptimization.cs."""
    data_bytes = bytes(data)
    rsc7 = struct.unpack_from("<I", data_bytes, 0)[0] if len(data_bytes) >= 4 else 0

    if rsc7 == 0x37435352:  # 'RSC7'
        import System  # type: ignore[import]
        net_data = System.Array[System.Byte](data_bytes)
        entry = cw["RpfFile"].CreateResourceFileEntry(net_data, 0)
        data_bytes = bytes(cw["ResourceBuilder"].Decompress(net_data))
    else:
        be = cw["RpfBinaryFileEntry"]()
        be.FileSize = len(data_bytes)
        be.FileUncompressedSize = be.FileSize
        entry = be

    entry.Name = name
    entry.NameLower = name.lower()
    entry.NameHash = cw["JenkHash"].GenHash(entry.NameLower)
    entry.ShortNameHash = cw["JenkHash"].GenHash(
        os.path.splitext(entry.NameLower)[0]
    )
    entry.Path = path
    return entry, data_bytes


def _load_ytd(cw, path: str):
    data = bytearray(Path(path).read_bytes())
    name = os.path.basename(path)
    entry, _ = _create_file_entry(cw, name, path, data)
    raw = bytes(Path(path).read_bytes())

    import System  # type: ignore[import]
    net_raw = System.Array[System.Byte](raw)
    ytd = cw["RpfFile"].GetFile[cw["YtdFile"]](entry, net_raw)
    return ytd


# ---------------------------------------------------------------------------
# texconv wrapper
# ---------------------------------------------------------------------------

def _run_texconv(
    texconv: str,
    dds_path: str,
    width: int,
    height: int,
    levels: int,
    fmt: str,
    verbose: bool,
) -> bool:
    """
    Run texconv.exe to convert/resize a DDS file in-place.
    The output is written next to the source file (texconv default).
    Returns True on success.
    """
    args = [
        texconv,
        "-w", str(width),
        "-h", str(height),
        "-m", str(levels),
        "-f", fmt,
        "-bc", "d",           # use GPU BC compression if available
        dds_path,
        "-y",                  # overwrite output
        "-o", str(Path(dds_path).parent),
    ]
    result = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if verbose:
        print("  texconv:", " ".join(args))
        if result.stdout:
            print("  stdout:", result.stdout.decode(errors="replace").strip())
        if result.stderr:
            print("  stderr:", result.stderr.decode(errors="replace").strip())
    return result.returncode == 0


# ---------------------------------------------------------------------------
# per-texture processing
# ---------------------------------------------------------------------------

def _process_texture(cw, texture, texconv: str, downsize: bool, format_optimize: bool, verbose: bool, tmpdir: str):
    """
    Optimise a single CodeWalker Texture object.
    Mirrors OptimizeTexture() in TextureOptimization.cs.
    Returns (new_texture, changed: bool).
    """
    import System  # type: ignore[import]

    fmt_name = str(texture.Format)
    texconv_fmt = _texconv_format(fmt_name, format_optimize)
    if texconv_fmt is None:
        if verbose:
            print(f"    skipping unknown format {fmt_name}")
        return texture, False

    # --- clamp mip levels ---
    min_side = min(texture.Width, texture.Height)
    max_level = int(math.log2(min_side))
    if texture.Levels >= max_level:
        texture.Levels = max_level - 1

    # --- write temp DDS ---
    tmp_dds = os.path.join(tmpdir, "temp.dds")
    try:
        dds_bytes = bytes(cw["DDSIO"].GetDDSFile(texture))
    except Exception as exc:
        if verbose:
            print(f"    DDSIO.GetDDSFile failed: {exc}")
        return texture, False
    Path(tmp_dds).write_bytes(dds_bytes)

    # --- apply downsize ---
    out_w, out_h = texture.Width, texture.Height
    out_levels = texture.Levels
    if downsize:
        out_w = max(1, texture.Width // 2)
        out_h = max(1, texture.Height // 2)
        out_levels = max(1, int(math.log2(min(out_w, out_h))) - 1)

    # --- run texconv ---
    ok = _run_texconv(texconv, tmp_dds, out_w, out_h, out_levels, texconv_fmt, verbose)
    if not ok:
        if verbose:
            print("    texconv failed, skipping texture")
        return texture, False

    # --- read converted DDS back ---
    try:
        new_dds = Path(tmp_dds).read_bytes()
        net_dds = System.Array[System.Byte](new_dds)
        new_tex = cw["DDSIO"].GetTexture(net_dds)
    except Exception as exc:
        if verbose:
            print(f"    failed to read converted DDS: {exc}")
        return texture, False

    texture.Data = new_tex.Data
    texture.Depth = new_tex.Depth
    texture.Levels = new_tex.Levels
    texture.Format = new_tex.Format
    texture.Stride = new_tex.Stride

    return texture, True


# ---------------------------------------------------------------------------
# main processing loop
# ---------------------------------------------------------------------------

def process_directory(
    cw,
    input_dir: str,
    backup_dir: str | None,
    min_size: int,
    only_oversized: bool,
    downsize: bool,
    format_optimize: bool,
    texconv: str,
    dry_run: bool,
    verbose: bool,
) -> dict:
    stats = {
        "files_scanned": 0,
        "files_changed": 0,
        "textures_changed": 0,
        "size_before_mb": 0.0,
        "size_after_mb": 0.0,
    }

    ytd_files = sorted(Path(input_dir).rglob("*.ytd"))
    total = len(ytd_files)
    if total == 0:
        print("No .ytd files found.")
        return stats

    with tempfile.TemporaryDirectory() as tmpdir:
        for idx, ytd_path in enumerate(ytd_files, 1):
            filepath = str(ytd_path)
            filename = ytd_path.name
            stats["files_scanned"] += 1

            v_mb, p_mb = get_rsc_sizes(filepath)

            print(f"[{idx}/{total}] {filename}  (physical {p_mb:.2f} MB)", end="")

            if v_mb == 0.0 and p_mb == 0.0:
                print("  — not RSC7, skipped")
                continue

            if only_oversized and p_mb <= 16.0:
                print("  — not oversized, skipped")
                continue

            if dry_run:
                print("  [dry-run]")
                continue

            # --- load YTD ---
            try:
                ytd = _load_ytd(cw, filepath)
            except Exception as exc:
                print(f"  — load failed: {exc}")
                continue

            textures = ytd.TextureDict.Textures
            ytd_changed = False
            tex_changed_count = 0

            for j in range(textures.Count):
                tex = textures.data_items[j]
                is_script = "script_rt" in tex.Name.lower()

                if is_script:
                    # skip script render targets
                    continue

                if tex.Width + tex.Height < min_size:
                    continue

                if verbose:
                    print(f"\n  texture [{j}] {tex.Name}  {tex.Width}x{tex.Height} {tex.Format}")

                # --- backup original on first change ---
                if not ytd_changed and backup_dir:
                    rel = ytd_path.relative_to(input_dir)
                    bak = Path(backup_dir) / rel
                    bak.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(filepath, bak)
                    except OSError as exc:
                        print(f"\n  backup failed: {exc}")

                new_tex, changed = _process_texture(
                    cw, tex, texconv, downsize, format_optimize, verbose, tmpdir
                )
                if changed:
                    textures.data_items[j] = new_tex
                    ytd_changed = True
                    tex_changed_count += 1

            if ytd_changed:
                try:
                    new_data = bytes(ytd.Save())
                    Path(filepath).write_bytes(new_data)
                    _, new_p_mb = get_rsc_sizes(filepath)
                    saved = p_mb - new_p_mb
                    print(f"  — saved {saved:.2f} MB  ({tex_changed_count} texture(s) changed)")
                    stats["files_changed"] += 1
                    stats["textures_changed"] += tex_changed_count
                    stats["size_before_mb"] += p_mb
                    stats["size_after_mb"] += new_p_mb
                except Exception as exc:
                    print(f"  — save failed: {exc}")
            else:
                print("  — nothing to change")

    return stats


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Downsize GTA V .ytd texture dictionary files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input", "-i", required=True, metavar="DIR",
                        help="Directory containing .ytd files (searched recursively)")
    parser.add_argument("--backup", "-b", metavar="DIR",
                        help="Copy original files here before modifying")
    parser.add_argument("--min-size", type=int, default=8192, metavar="N",
                        help="Only optimize textures where width+height >= N  [default: 8192]")
    parser.add_argument("--downsize", dest="downsize", action="store_true", default=True,
                        help="Halve texture dimensions (default)")
    parser.add_argument("--no-downsize", dest="downsize", action="store_false",
                        help="Do not halve texture dimensions")
    parser.add_argument("--format-optimize", action="store_true",
                        help="Force all textures to BC1/BC3 regardless of source format")
    parser.add_argument("--only-oversized", action="store_true",
                        help="Skip files whose physical size is <= 16 MB")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be processed without writing anything")
    parser.add_argument("--texconv", metavar="PATH",
                        help="Path to texconv.exe  [default: auto-detect]")
    parser.add_argument("--dll", metavar="PATH",
                        help="Path to CodeWalker.Core.dll  [default: auto-detect]")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Extra logging")
    args = parser.parse_args()

    # --- resolve texconv ---
    texconv = args.texconv or _find_sibling("texconv.exe")
    if not texconv:
        print("ERROR: texconv.exe not found. Provide --texconv or place it in Application/Dependencies/.")
        sys.exit(1)
    print(f"texconv: {texconv}")

    # --- resolve CodeWalker dll ---
    dll = args.dll or _find_sibling("CodeWalker.Core.dll")
    if not dll:
        print("ERROR: CodeWalker.Core.dll not found. Provide --dll or place it in Application/Dependencies/.")
        sys.exit(1)
    print(f"CodeWalker.Core.dll: {dll}")

    # --- load CodeWalker ---
    try:
        cw = _load_codewalker(dll)
    except ImportError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    # --- validate input directory ---
    input_dir = os.path.abspath(args.input)
    if not os.path.isdir(input_dir):
        print(f"ERROR: input directory does not exist: {input_dir}")
        sys.exit(1)

    backup_dir = os.path.abspath(args.backup) if args.backup else None

    print(f"\nInput:       {input_dir}")
    if backup_dir:
        print(f"Backup:      {backup_dir}")
    print(f"Min size:    width+height >= {args.min_size}")
    print(f"Downsize:    {args.downsize}")
    print(f"Fmt-opt:     {args.format_optimize}")
    print(f"Oversized:   {args.only_oversized}")
    print(f"Dry run:     {args.dry_run}")
    print()

    stats = process_directory(
        cw=cw,
        input_dir=input_dir,
        backup_dir=backup_dir,
        min_size=args.min_size,
        only_oversized=args.only_oversized,
        downsize=args.downsize,
        format_optimize=args.format_optimize,
        texconv=texconv,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    print()
    print("=== Summary ===")
    print(f"Files scanned:   {stats['files_scanned']}")
    print(f"Files changed:   {stats['files_changed']}")
    print(f"Textures changed:{stats['textures_changed']}")
    if stats["files_changed"]:
        saved = stats["size_before_mb"] - stats["size_after_mb"]
        pct = 100 * saved / stats["size_before_mb"] if stats["size_before_mb"] else 0
        print(f"Size saved:      {saved:.2f} MB  ({pct:.1f}%)")


if __name__ == "__main__":
    main()
