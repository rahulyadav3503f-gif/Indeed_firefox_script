"""New Indeed collector -- Firefox / xdotool / xclip browser automation.

The modules the brief asks for (section 5), and nothing else:

    indeed_controller.py   Python <-> shell bridge: windows, keys, clipboard
    indeed_extractor.py    clipboard text -> the 32-column row
    indeed_excel.py        safe Excel append, rollover and backup
    indeed_checkpoint.py   per-rank checkpoints incl. total_complete_cycle
    indeed_validator.py    validation, non-IT filtering, duplicate detection

Every editable setting lives at the top of ``find_indeed_job.py`` and is
passed in, exactly as the original project does it, so this package holds
behaviour only.
"""
