#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
bulk_bake_anim_into_m2.py — batch version of merge_anim_into_m2.py.

Point it at a folder. For every chunked .m2 file in that folder, it looks
for that model's own external .anim files sitting alongside it (matched by
the standard "<model stem><NNNN>-<SS>.anim" naming convention -- SAME
convention merge_anim_into_skel.anim_id_subid_from_filename() already
parses), bakes every match it finds directly into that .m2's own MD20
bones/sequences (via merge_anim_into_m2.merge_anim_into_m2(), unchanged),
and writes the result into a "baked" subfolder, under the original .m2's
filename.

IMPORTANT -- which .anim files this handles:
  This bakes AFM2-chunk .anim files (the legacy, pre-.skel layout, matching
  bones embedded directly in the .m2's own MD20) straight into the .m2.
  It does NOT touch .anim files that only carry AFSB (the modern .skel/SKB1
  layout) -- those go through merge_anim_into_skel.py instead, against a
  .skel, not an .m2. See merge_anim_into_m2.py's docstring for the full
  AFM2-vs-AFSB explanation. A .m2 must ALSO already be self-contained
  (non-empty bones/sequences in its own MD20) before anything here can bake
  into it -- run merge_skel_into_m2.py first if it isn't.

Matching rule (per .m2 file "Foo.m2"):
  Any file in the same folder named exactly "Foo" + "NNNN-SS.anim"
  (4 digits, '-', 2 digits, case-insensitive on the .anim extension) is
  considered one of Foo's own anims. This is a plain prefix match against
  the .m2's own filename stem -- so "Foo.m2" will NOT accidentally match
  "FooBar0001-00.anim" (that file's stem is "FooBar", not "Foo"; matching
  is done by first stripping the trailing "NNNN-SS" tail and comparing
  what's left to the .m2 stem exactly, not with startswith()).

Usage:
    python3 bulk_bake_anim_into_m2.py [--force-all-embedded] <folder>

Output:
    <folder>/baked/<same .m2 filename>, one per input .m2 that had at
    least one matching .anim (an .m2 with zero matches is skipped, not
    copied verbatim -- see the summary printed at the end).
"""
from __future__ import print_function
import os
import re
import struct
import sys

import merge_anim_into_m2 as mam       # merge_anim_into_m2(), load_anim_afm2()

ANIM_TAIL_RE = re.compile(r'^(.*)(\d{4})-(\d{2})$')


def anim_stem_and_ids(anim_filename):
    """
    Splits an .anim filename (no directory, no extension) into
    (model_stem, animID, subID), or returns None if it doesn't match the
    "...NNNN-SS" tail convention at all (so it's silently skipped rather
    than raising -- a bulk scan will see plenty of unrelated files).
    """
    stem = os.path.splitext(anim_filename)[0]
    m = ANIM_TAIL_RE.match(stem)
    if not m:
        return None
    model_stem, anim_id, sub_id = m.group(1), int(m.group(2)), int(m.group(3))
    return model_stem, anim_id, sub_id


def find_m2_files(folder):
    return sorted(f for f in os.listdir(folder)
                  if f.lower().endswith('.m2') and os.path.isfile(os.path.join(folder, f)))


def find_matching_anims(folder, m2_stem, all_entries):
    """
    all_entries: pre-listed directory contents (avoid re-listdir()'ing the
    folder once per .m2 file -- fine either way, but cheap to share).
    Returns a sorted list of full paths, sorted by (animID, subID) so the
    printed bake order is stable/predictable across runs.
    """
    matches = []
    for entry in all_entries:
        if not entry.lower().endswith('.anim'):
            continue
        parsed = anim_stem_and_ids(entry)
        if parsed is None:
            continue
        model_stem, anim_id, sub_id = parsed
        if model_stem == m2_stem:
            matches.append((anim_id, sub_id, os.path.join(folder, entry)))
    matches.sort(key=lambda t: (t[0], t[1]))
    return [path for _, _, path in matches]


def bulk_bake(folder, force_all_embedded=False):
    if not os.path.isdir(folder):
        raise ValueError("%s is not a folder" % folder)

    all_entries = os.listdir(folder)
    m2_files = find_m2_files(folder)
    if not m2_files:
        print("No .m2 files found in %s" % folder)
        return

    out_dir = os.path.join(folder, 'baked')
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    baked_ok = []
    skipped_no_anims = []
    failed = []

    for m2_name in m2_files:
        m2_stem = os.path.splitext(m2_name)[0]
        m2_path = os.path.join(folder, m2_name)
        anim_paths = find_matching_anims(folder, m2_stem, all_entries)

        if not anim_paths:
            print("[skip] %s: no matching .anim files found (looked for \"%sNNNN-SS.anim\")"
                  % (m2_name, m2_stem))
            skipped_no_anims.append(m2_name)
            continue

        print("[m2] %s: found %d matching .anim file(s)" % (m2_name, len(anim_paths)))
        for p in anim_paths:
            print("       %s" % os.path.basename(p))

        out_path = os.path.join(out_dir, m2_name)
        try:
            mam.merge_anim_into_m2(m2_path, out_path, anim_paths,
                                    force_all_embedded=force_all_embedded)
            baked_ok.append(m2_name)
        except Exception as e:
            print("  [error] failed to bake %s: %s" % (m2_name, e))
            failed.append((m2_name, str(e)))
        print("")

    print("=" * 60)
    print("Done. %d baked, %d skipped (no matching .anim), %d failed."
          % (len(baked_ok), len(skipped_no_anims), len(failed)))
    if baked_ok:
        print("  baked: %s" % ", ".join(baked_ok))
    if skipped_no_anims:
        print("  skipped: %s" % ", ".join(skipped_no_anims))
    if failed:
        print("  failed:")
        for name, err in failed:
            print("    - %s: %s" % (name, err))


def main():
    args = sys.argv[1:]
    force_all_embedded = '--force-all-embedded' in args
    if force_all_embedded:
        args = [a for a in args if a != '--force-all-embedded']

    if len(args) != 1:
        print("Usage: python3 bulk_bake_anim_into_m2.py [--force-all-embedded] <folder>")
        print("  Scans <folder> for .m2 files, and for each one bakes any matching")
        print("  \"<m2 stem>NNNN-SS.anim\" files (AFM2 chunk) found in the same folder")
        print("  directly into that .m2's own MD20 bones/sequences (must already be")
        print("  self-contained -- run merge_skel_into_m2.py first if it isn't).")
        print("  Output goes to <folder>/baked/<same .m2 filename>.")
        print("  --force-all-embedded: forwarded to merge_anim_into_m2.py for each file --")
        print("                        also forces the embedded flag on every OTHER")
        print("                        sequence that had no baked .anim data of its own.")
        sys.exit(1)

    bulk_bake(args[0], force_all_embedded=force_all_embedded)


if __name__ == '__main__':
    main()
