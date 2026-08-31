#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一入口：一个 EXE 搞定所有功能
- 双击 / 无参数 → 启动 GUI
- 命令行带参数 → 调用对应 CLI 工具
"""
from __future__ import print_function
import sys
import os

# 确保同级目录的模块能被导入（PyInstaller 打包后依然有效）
HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SUBCOMMANDS = {
    'skel': {
        'desc': 'Merge parent + daughter .skel',
        'usage': 'skel <parent.skel> <daughter.skel> <out.skel>',
        'argc': 3,
    },
    'anim-into-skel': {
        'desc': 'Bake .anim files into a .skel',
        'usage': 'anim-into-skel [--force-all-embedded] <parent.skel> <out.skel> <anim1.anim> [anim2.anim ...]',
        'argc': 2,  # 最小参数，实际可变
    },
    'skel-into-m2': {
        'desc': 'Bake a .skel into a .m2',
        'usage': 'skel-into-m2 <model.m2> <skeleton.skel> <out.m2>',
        'argc': 3,
    },
    'anim-into-m2': {
        'desc': 'Bake .anim directly into a .m2 (no .skel)',
        'usage': 'anim-into-m2 [--force-all-embedded] <model.m2> <out.m2> <anim1.anim> [anim2.anim ...]',
        'argc': 2,
    },
    'bulk-anim-into-m2': {
        'desc': 'Bulk bake .anim into a folder of .m2',
        'usage': 'bulk-anim-into-m2 [--force-all-embedded] <folder>',
        'argc': 1,
    },
}


def print_help():
    print("WoW Skel Merge Tool - Unified CLI/GUI")
    print("")
    print("Usage:")
    print("  wow_skel_merge.exe           Launch GUI (no arguments)")
    print("  wow_skel_merge.exe <cmd> ... Run a command-line tool")
    print("")
    print("Commands:")
    for cmd, info in SUBCOMMANDS.items():
        print("  %-20s %s" % (cmd, info['desc']))
        print("    %s" % info['usage'])
    print("")
    print("Examples:")
    print('  wow_skel_merge.exe skel parent.skel daughter.skel merged.skel')
    print('  wow_skel_merge.exe anim-into-skel skeleton.skel out.skel anim.anim')
    print('  wow_skel_merge.exe skel-into-m2 model.m2 skeleton.skel out.m2')
    print('  wow_skel_merge.exe anim-into-m2 model.m2 out.m2 anim1.anim anim2.anim')
    print('  wow_skel_merge.exe bulk-anim-into-m2 "C:\\path\\to\\folder"')


def launch_gui():
    try:
        import merge_skel_gui
        app = merge_skel_gui.MergeSkelApp()
        app.mainloop()
    except Exception as e:
        import traceback
        print("Failed to start GUI: %s" % e)
        traceback.print_exc()
        sys.exit(1)


def main():
    args = sys.argv[1:]

    # 无参数 → 启动 GUI
    if not args or args[0] in ('--gui', '-g'):
        launch_gui()
        return

    # --help / -h
    if args[0] in ('--help', '-h', '/?'):
        print_help()
        return

    cmd = args[0]
    rest = args[1:]

    if cmd == 'skel':
        if len(rest) < 3:
            print("Usage: wow_skel_merge.exe skel <parent.skel> <daughter.skel> <out.skel>")
            sys.exit(1)
        import merge_skel as ms
        ms.main_argv = rest  # 直接传参
        # merge_skel.py 的 main() 读 sys.argv，我们替换一下
        old_argv = sys.argv
        sys.argv = ['merge_skel.py'] + rest
        try:
            ms.main()
        finally:
            sys.argv = old_argv

    elif cmd == 'anim-into-skel':
        if len(rest) < 3:
            print("Usage: wow_skel_merge.exe anim-into-skel [--force-all-embedded] <skel> <out> <anim>...")
            sys.exit(1)
        import merge_anim_into_skel as mais
        old_argv = sys.argv
        sys.argv = ['merge_anim_into_skel.py'] + rest
        try:
            mais.main()
        finally:
            sys.argv = old_argv

    elif cmd == 'skel-into-m2':
        if len(rest) < 3:
            print("Usage: wow_skel_merge.exe skel-into-m2 <model.m2> <skeleton.skel> <out.m2>")
            sys.exit(1)
        import merge_skel_into_m2 as msm
        old_argv = sys.argv
        sys.argv = ['merge_skel_into_m2.py'] + rest
        try:
            msm.main()
        finally:
            sys.argv = old_argv

    elif cmd == 'anim-into-m2':
        if len(rest) < 3:
            print("Usage: wow_skel_merge.exe anim-into-m2 [--force-all-embedded] <model.m2> <out.m2> <anim>...")
            sys.exit(1)
        import merge_anim_into_m2 as maim
        old_argv = sys.argv
        sys.argv = ['merge_anim_into_m2.py'] + rest
        try:
            maim.main()
        finally:
            sys.argv = old_argv

    elif cmd == 'bulk-anim-into-m2':
        if len(rest) < 1:
            print("Usage: wow_skel_merge.exe bulk-anim-into-m2 [--force-all-embedded] <folder>")
            sys.exit(1)
        import bulk_bake_anim_into_m2 as bulk
        old_argv = sys.argv
        sys.argv = ['bulk_bake_anim_into_m2.py'] + rest
        try:
            bulk.main()
        finally:
            sys.argv = old_argv

    else:
        print("Unknown command: %s" % cmd)
        print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()