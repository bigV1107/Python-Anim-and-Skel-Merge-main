#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
merge_anim_into_m2.py — bakes one or more external chunked .anim files
directly into a chunked (Legion+) .m2's OWN embedded MD20 bones/sequences,
without going through a .skel at any point.

PREREQUISITE: the .m2 must already be self-contained -- i.e. its MD20
bones/sequences arrays are non-empty (either because it's an old-style
pre-.skel .m2, or because merge_skel_into_m2.py already folded a .skel
into it). If bones/sequences are still empty (count=0), the model still
depends on an external .skel and there's nothing here yet to bake .anim
data into -- run merge_skel_into_m2.py first (optionally together with
merge_anim_into_skel.py), then run this tool on the result if you still
have un-embedded animations left.

WHICH .anim CHUNK THIS TOOL READS -- AFM2, NOT AFSB:
  Chunked (Legion+) .anim files can carry two different chunks, and which
  one(s) are present depends on what kind of model they're paired with:
    - AFSB: per-bone track data laid out to match a .skel's SKB1 -- for
      models that go through the modern .skel/SKB1 pipeline. This is what
      merge_anim_into_skel.py (and merge_skel_into_m2.py's own --anim
      option, if present) consumes.
    - AFM2: the legacy, pre-.skel raw layout -- for models whose bones are
      embedded directly in the .m2's own MD20 (no .skel involved at all).
      This is verified byte-for-byte identical in struct layout to
      M2CompBone (see merge_skel_into_m2.py's docstring), so it's the
      correct buffer to re-read track values from when baking into an
      already-self-contained .m2, which is exactly this tool's job.
  A .anim file may have only AFM2, only AFSB, or both, depending on how it
  was produced. This tool specifically needs AFM2 and will tell you if a
  file only has AFSB (that file is for merge_anim_into_skel.py instead).

Mechanism (identical trick to merge_anim_into_skel.py, just applied to the
.m2's own M2Header-referenced bones/sequences arrays instead of a .skel's
SKB1/SKS1 chunks):

  For a sequence NOT yet embedded (M2Sequence.flags & 0x20 == 0, meaning
  the client loads it from an external .anim file), every bone's
  translation/rotation/scaling track already contains a correct-looking
  (count, offset) descriptor pair at that sequence's index -- but the
  offset is relative to the *external* .anim file's AFM2 chunk payload,
  not to MD20. Baking == re-reading those (count, offset) pairs against
  the external AFM2 buffer instead of MD20's own bytes, splicing the
  resulting real values into the bones, appending a freshly-serialized
  bones array (existing tracks preserved as-is; only the given sequence
  indices get real data), pointing the M2Header at the new array, and
  setting flags |= 0x20 on the affected M2Sequence record(s). The old
  bones array bytes are left orphaned in the file (same append-only,
  don't-reshuffle-existing-data strategy as merge_skel_into_m2.py).

Usage:
    python3 merge_anim_into_m2.py [--force-all-embedded] model.m2 out.m2 anim1.anim [anim2.anim ...]
"""
from __future__ import print_function
import struct
import sys

import merge_skel as ms                # BONE_*/TRACK_*/ANIM_SIZE constants, write_skb1()
import merge_anim_into_skel as ma      # anim_id_subid_from_filename(), build_skb1_for_write(), alias logic
import merge_skel_into_m2 as mm        # load_m2_chunks(), find_chunk(), rebase_skb1(), header offsets


def load_anim_afm2(path):
    """
    Returns (animID, subID, afm2_payload_bytes) for a chunked .anim file's
    AFM2 chunk -- the legacy/pre-.skel layout that matches an .m2's own
    directly-embedded M2CompBone track offsets (see this module's
    docstring for why AFM2, not AFSB, is the right chunk for this tool).

    Unlike merge_anim_into_skel.load_anim_afsb() (which requires AFSB),
    this only requires AFM2 to be present -- many .anim files that pair
    with non-.skel models carry AFM2 alone, with no AFSB chunk at all.
    """
    data = open(path, 'rb').read()
    off = 0
    chunks = {}
    while off < len(data):
        magic = data[off:off + 4].decode('ascii')
        size = struct.unpack_from('<I', data, off + 4)[0]
        chunks[magic] = data[off + 8:off + 8 + size]
        off += 8 + size

    if 'AFM2' not in chunks:
        raise ValueError(
            "%s doesn't look like a valid chunked .anim file (missing the AFM2 chunk)." % path
        )

    anim_id, sub_id = ma.anim_id_subid_from_filename(path)
    return anim_id, sub_id, chunks['AFM2']


# ---------------------------------------------------------------------------
# Read the .m2's own bones/sequences arrays directly out of MD20 (base 0 --
# M2Array offsets in a model file are always relative to the start of MD20).
# ---------------------------------------------------------------------------

def parse_bones_raw_offsets(ro, nBones, oBones):
    """Like merge_anim_into_skel.parse_skb1_with_raw_offsets(), but reading
    straight out of an MD20 buffer at caller-supplied (nBones, oBones)
    instead of assuming a chunk-local SKB1 header -- the .m2's M2Header
    already gives us those two values directly.

    `ro` must be a plain bytes/str snapshot, NOT a bytearray: Python 2's
    struct.unpack_from() doesn't accept a bytearray (only str/buffer),
    unlike Python 3 -- see the same note in merge_skel_into_m2.rebase_skb1().
    """
    bones = []
    pos = oBones
    for i in range(nBones):
        key_bone_id, flags, parent_bone, submesh_id, crc = struct.unpack_from(
            ms.BONE_HDR_FMT, ro, pos)
        p = pos + ms.BONE_HDR_SIZE
        comps = {}
        for comp, kind in (('translation', 'vec'), ('rotation', 'rot'), ('scaling', 'vec')):
            interp, gseq, nts, ots, nkf, okf = struct.unpack_from(ms.TRACK_HDR_FMT, ro, p)
            ts_pairs = [struct.unpack_from('<ii', ro, ots + j * 8) for j in range(nts)] if nts else []
            kf_pairs = [struct.unpack_from('<ii', ro, okf + j * 8) for j in range(nkf)] if nkf else []
            comps[comp] = {
                'interp': interp, 'gseq': gseq,
                'ts_pairs': ts_pairs, 'kf_pairs': kf_pairs,
                'kind': kind,
            }
            p += ms.TRACK_HDR_SIZE
        pivot = struct.unpack_from('<3f', ro, p)
        bones.append({
            'key_bone_id': key_bone_id, 'flags': flags, 'parent_bone': parent_bone,
            'submesh_id': submesh_id, 'crc': crc, 'pivot': pivot, 'comps': comps,
        })
        pos += ms.BONE_SIZE
    return bones


def parse_sequences_raw(ro, nSeq, oSeq):
    """`ro` must be bytes/str, not a bytearray -- see parse_bones_raw_offsets()."""
    anims = []
    for i in range(nSeq):
        raw = ro[oSeq + i * ms.ANIM_SIZE: oSeq + (i + 1) * ms.ANIM_SIZE]
        animID, subID = struct.unpack_from('<HH', raw, 0)
        anims.append({'animID': animID, 'subID': subID, 'raw': raw})
    return anims


# ---------------------------------------------------------------------------
# Bake .anim files into the .m2's in-memory MD20 buffer
# ---------------------------------------------------------------------------

def bake_anims_into_m2(md20, anim_paths, force_all_embedded=False):
    """
    md20: bytearray of the .m2's MD21 payload (mutated for the sequence
    flags; the bones array itself gets rebuilt and appended, not mutated
    in place -- same append-only approach as merge_skel_into_m2.py).
    Returns the new md20 bytearray (same object, for convenience) and the
    set of (animID, subID) pairs that got real track data baked in.
    """
    # Snapshot: Python 2's struct.unpack_from() doesn't accept a bytearray
    # (only str/buffer), unlike Python 3 -- see rebase_skb1()'s note. Every
    # read below happens strictly before md20 gets mutated further down, so
    # a snapshot here never goes stale mid-function.
    ro = bytes(md20)

    nSeq, oSeq = struct.unpack_from('<II', ro, mm.OFS_SEQUENCES)
    nBones, oBones = struct.unpack_from('<II', ro, mm.OFS_BONES)
    nKBL, oKBL = struct.unpack_from('<II', ro, mm.OFS_BONE_LOOKUP)

    if not nSeq or not nBones:
        raise ValueError(
            "this .m2's own bones/sequences arrays are empty (count=0) -- it still "
            "depends on an external .skel for those. Run merge_skel_into_m2.py first "
            "(optionally with its own --anim support, if present) so there's something "
            "here to bake .anim data into, then re-run this tool on that output."
        )

    anims = parse_sequences_raw(ro, nSeq, oSeq)
    bones = parse_bones_raw_offsets(ro, nBones, oBones)
    keybonelookup = list(struct.unpack_from('<%dh' % nKBL, ro, oKBL)) if nKBL else []
    raw_skb1 = {'bones': bones, 'keybonelookup': keybonelookup}

    local_payload = ro   # source buffer for any (n, o) pair NOT overridden by an .anim
    overrides = {}                 # anim_index -> afsb bytes
    embedded_animid_subid = set()

    def _flags_of(i):
        return struct.unpack_from('<I', anims[i]['raw'], ma.SKS1_FLAGS_OFFSET)[0]

    for anim_path in anim_paths:
        anim_id, sub_id, afm2 = load_anim_afm2(anim_path)
        matches = [i for i, a in enumerate(anims) if a['animID'] == anim_id and a['subID'] == sub_id]
        if not matches:
            raise ValueError(
                "%s: animID=%d subID=%d has no matching M2Sequence entry in this .m2 -- "
                "can't bake in an animation the model doesn't know about." % (anim_path, anim_id, sub_id)
            )

        non_alias = [i for i in matches if not (_flags_of(i) & ma.SKS1_ALIAS_FLAG)]
        primary_idx = non_alias[0] if non_alias else matches[0]

        print("  baking animID=%d subID=%d -> sequence index %d (from %s)"
              % (anim_id, sub_id, primary_idx, anim_path))
        overrides[primary_idx] = afm2
        embedded_animid_subid.add((anim_id, sub_id))

        if len(matches) > 1:
            print("  %d other sequence entries share animID=%d subID=%d (aliases) -- "
                  "flagging them embedded too, without duplicating track data: %s"
                  % (len(matches) - 1, anim_id, sub_id, [i for i in matches if i != primary_idx]))

        for idx in matches:
            raw = anims[idx]['raw']
            flags = struct.unpack_from('<I', raw, ma.SKS1_FLAGS_OFFSET)[0]
            if flags & ma.SKS1_EMBEDDED_FLAG:
                print("  [info] animID=%d subID=%d (index %d) already has the "
                      "embedded flag set -- leaving as-is." % (anim_id, sub_id, idx))
                continue
            new_raw = bytearray(raw)
            struct.pack_into('<I', new_raw, ma.SKS1_FLAGS_OFFSET, flags | ma.SKS1_EMBEDDED_FLAG)
            anims[idx] = dict(anims[idx])
            anims[idx]['raw'] = bytes(new_raw)

    if force_all_embedded:
        forced = 0
        skipped_aliases = 0
        for idx, a in enumerate(anims):
            raw = a['raw']
            flags = struct.unpack_from('<I', raw, ma.SKS1_FLAGS_OFFSET)[0]
            if flags & ma.SKS1_EMBEDDED_FLAG:
                continue
            if flags & ma.SKS1_ALIAS_FLAG:
                skipped_aliases += 1
                continue
            new_raw = bytearray(raw)
            struct.pack_into('<I', new_raw, ma.SKS1_FLAGS_OFFSET, flags | ma.SKS1_EMBEDDED_FLAG)
            anims[idx] = dict(a)
            anims[idx]['raw'] = bytes(new_raw)
            forced += 1
        if forced:
            print("  [force-embedded] set flag 0x20 on %d additional sequence entries that had no "
                  "baked .anim data of their own -- see merge_anim_into_skel.py's docstring for "
                  "the caveats before relying on this." % forced)
        if skipped_aliases:
            print("  [force-embedded] left %d genuine alias entries (flags & 0x40) untouched."
                  % skipped_aliases)

    merged_skb1 = ma.build_skb1_for_write(raw_skb1, local_payload, overrides)

    bad = 0
    for bi, bone in enumerate(merged_skb1['bones']):
        for comp in ('translation', 'rotation', 'scaling'):
            for kind, lst in (('ts', bone[comp]['timestamps']), ('kf', bone[comp]['keyframes'])):
                for i, v in enumerate(lst):
                    if v is None:
                        bad += 1
                        if bad <= 10:
                            print("  [warn] bone %d %s %s index %d: offset out of range, "
                                  "left empty instead of corrupting" % (bi, comp, kind, i))
                        lst[i] = []
    if bad:
        print("  [warn] %d sub-blocks could not be resolved (see above) -- "
              "output written anyway but review those bones/animations." % bad)

    sks1_like = {'anims': anims}
    ma.resolve_sequence_aliases(sks1_like, merged_skb1)
    anims = sks1_like['anims']

    # 1) write updated sequence records back in place (same size, no reshuffle)
    for i, a in enumerate(anims):
        md20[oSeq + i * ms.ANIM_SIZE: oSeq + (i + 1) * ms.ANIM_SIZE] = a['raw']

    # 2) append a freshly-serialized, self-contained bones array and rebase it
    bones_base = len(md20)
    skb1_raw = ms.write_skb1(merged_skb1)
    n_b, ofsBones_l, nKBL_l, ofsKBL_l = struct.unpack_from('<4I', skb1_raw, 0)
    skb1_blob = mm.rebase_skb1(skb1_raw, bones_base)
    md20.extend(skb1_blob)

    struct.pack_into('<II', md20, mm.OFS_BONES, n_b, bones_base + ofsBones_l if n_b else 0)
    struct.pack_into('<II', md20, mm.OFS_BONE_LOOKUP, nKBL_l, bones_base + ofsKBL_l if nKBL_l else 0)

    print("  bones: %d entries at %d (old bones array left orphaned in the file)"
          % (n_b, bones_base + ofsBones_l if n_b else 0))
    print("  boneIndicesById: %d entries at %d" % (nKBL_l, bones_base + ofsKBL_l if nKBL_l else 0))

    return md20, embedded_animid_subid


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def merge_anim_into_m2(m2_path, out_path, anim_paths, force_all_embedded=False):
    m2_chunks = mm.load_m2_chunks(m2_path)
    md21 = mm.find_chunk(m2_chunks, 'MD21')
    if md21 is None:
        raise ValueError("%s has no MD21 chunk -- doesn't look like a chunked (Legion+) .m2" % m2_path)
    md20 = bytearray(md21[1])

    md20, embedded = bake_anims_into_m2(md20, anim_paths, force_all_embedded=force_all_embedded)

    out_chunks = []
    for magic, payload in m2_chunks:
        if magic == 'MD21':
            out_chunks.append((magic, bytes(md20)))
        else:
            out_chunks.append((magic, payload))

    out_bytes = bytearray()
    for magic, payload in out_chunks:
        out_bytes += magic.encode('ascii')
        out_bytes += struct.pack('<I', len(payload))
        out_bytes += payload

    with open(out_path, 'wb') as f:
        f.write(out_bytes)
    print("Written: %s (%d bytes)" % (out_path, len(out_bytes)))
    print("Baked %d animation(s): %s" % (len(embedded), sorted(embedded)))


def main():
    args = sys.argv[1:]
    force_all_embedded = '--force-all-embedded' in args
    if force_all_embedded:
        args = [a for a in args if a != '--force-all-embedded']

    if len(args) < 3:
        print("Usage: python3 merge_anim_into_m2.py [--force-all-embedded] <model.m2> <out.m2> <anim1.anim> [anim2.anim ...]")
        print("  requires model.m2 to already have its own bones/sequences embedded directly")
        print("  in MD20 (e.g. the output of merge_skel_into_m2.py) -- it does NOT read a .skel.")
        print("  --force-all-embedded: after baking the given .anim file(s), also force the")
        print("                        embedded flag (0x20) on every OTHER sequence in the .m2")
        print("                        (except genuine aliases). See merge_anim_into_skel.py's")
        print("                        docstring for the caveats before relying on this.")
        sys.exit(1)

    m2_path, out_path = args[0], args[1]
    anim_paths = args[2:]
    merge_anim_into_m2(m2_path, out_path, anim_paths, force_all_embedded=force_all_embedded)


if __name__ == '__main__':
    main()
