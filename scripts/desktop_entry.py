import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from zju_ac.desktop.app import main

    raise SystemExit(main())
