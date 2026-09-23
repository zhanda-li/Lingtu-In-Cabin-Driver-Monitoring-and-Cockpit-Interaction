@echo off
rem ============================================================
rem  Double-click this file for the FUSED demo (branch 1 + branch 2).
rem
rem  branch 1 = pose skeleton -> Transformer -> 4 classes  (distraction)
rem  branch 2 = FaceMesh EAR/MAR  -> logistic regression   (eye closure)
rem  The gate lets branch 2 vote only while branch 1 says "normal".
rem
rem  NOTE: this file must contain ASCII ONLY.
rem  cmd.exe parses .bat files with the system ANSI codepage (GBK on
rem  this machine), so UTF-8 Chinese text here corrupts the parsing
rem  and breaks every following line. All Chinese output is printed
rem  by the Python program instead (config.py forces UTF-8 stdout).
rem
rem  Every run writes its OWN log - runs\session1.csv, session2.csv, ...
rem  Nothing is ever overwritten (it picks the first free number).
rem  To force a name yourself, pass one (argparse takes the last):
rem      live_fuse.bat --log-probs runs\eyes_only.csv
rem
rem  SPACE toggles a MARK while it runs - press it when you close your
rem  eyes on purpose. It is written into fuse.csv and is the ground
rem  truth for the L4 verdict, which is a separate step afterwards:
rem      python tools\analyze_fuse_l4.py fuse.csv --png runs\fuse_l4.png
rem  Without marks the verdict can only fall back on the sliding-window
rem  argument, whose stratifying variable is head movement - i.e. the
rem  very thing it is supposed to rule out. So: USE THE SPACE BAR.
rem
rem  Branch 2 needs 27 s of CONTINUOUSLY open gate before it says
rem  anything, and a closed gate wipes that warm-up. So the session has
rem  phases - the order is printed below, follow it.
rem
rem  Any other arguments are passed through to src\fuse.py, e.g.
rem      live_fuse.bat --replay data\raw\fatigue\fatigue_02.mp4
rem      live_fuse.bat --seconds 30
rem      live_fuse.bat --no-face          (equals plain src\live.py)
rem      live_fuse.bat --face-hz 7         (if the CPU cannot keep up)
rem      live_fuse.bat --selftest data\raw\fatigue\fatigue_02.mp4
rem ============================================================
chcp 65001 >nul
rem Repair PATH: when cmd is launched from a garbled environment the
rem drive-letter colons get mangled, which breaks the python lookup.
set "PATH=C:\Windows\System32;C:\Windows;%PATH%"
cd /d "%~dp0"

echo Starting the FUSED realtime demo. Press Q or ESC in the window to quit.
echo Need a light source: below ~12 fps both branches get coarse.
echo Every decision is saved to a fresh file under runs\ - see below.
echo.
echo ============================================================
echo  HOW TO RUN THIS SESSION - the phases matter, do them in order
echo ============================================================
echo.
echo  0. BEFORE YOU START
echo     - Click ONCE on the video window. Keys only reach the program
echo       while that window has focus. If the black console has focus,
echo       SPACE goes nowhere and every mark is silently lost.
echo     - Light. Watch the top-left "cam x.x fps". Below 12 the whole
echo       pipeline gets coarse. Turn on a desk lamp.
echo     - The camera must see your whole upper body with BOTH SHOULDERS
echo       in frame - shoulder width is the scale reference.
echo     - Sit up straight. Do not slouch into the chair.
echo.
echo  SPACE = mark. Toggle it ON when you shut your eyes on purpose,
echo  toggle it OFF when you open them. It changes nothing in the
echo  program - it only writes a column into fuse.csv and prints the
echo  time. It is the ground truth the verdict script needs.
echo.
echo  THE WHOLE SESSION IS RUN BLIND - this is the part people get wrong.
echo  Any look at the screen moves your head and can CLOSE the gate,
echo  which wipes the 27 s warm-up and starts it over. So do NOT read
echo  numbers while it runs. They are all in the CSV afterwards; that is
echo  what the log is for. Live, you watch exactly two COLOURS:
echo      MARK   magenta = your SPACE press registered
echo      gate   bright green = open     blue = CLOSED, warm-up wiped
echo  Best case: have someone else watch the panel and tell you. If you
echo  are alone, count seconds in your head. Do not turn to look.
echo.
echo  A. WARM-UP, about 35 s
echo     Sit up straight, shoulders in frame. Look at the CAMERA LENS
echo     itself, not at the screen. Keep still and count to 35.
echo     Branch 2 needs 27 s of CONTINUOUS open gate before it can say
echo     anything at all. Before that it is mute: P(fat) reads as a dash.
echo     (The panel wording changes at 10 s and again at 27 s - ignore it,
echo      just count. If you got it wrong the CSV shows it and you redo.)
echo.
echo  B. BASELINE, about 20 s
echo     Keep sitting still, looking straight ahead, eyes open, relaxed.
echo     This stretch is your floor. It is being recorded - do not read it.
echo.
echo  C. EYES SHUT - 8 reps of 5 s   *** THE ONE THAT MATTERS ***
echo     Lean the back of your head on the chair so it CANNOT sink on its
echo     own. Then, once per rep:
echo        SPACE (MARK turns magenta)
echo        shut your eyes, count to 5 - no longer
echo        SPACE again (MARK greys out)
echo        open your eyes, count to 12 before starting the next rep
echo     NEVER hold your eyes shut longer than about 5 s, and never skip
echo     the 12 s rest. Reason: the normalisation baseline is a 75th
echo     percentile over a 10 s window, and it only stays valid while eye
echo     closure is under ~75% of that window. Hold your eyes shut for
echo     12 s and the window is ~100% closed: the baseline collapses onto
echo     the closed-eye value, EAR_norm reads ~0.9 for CLOSED eyes, and
echo     the measurement destroys itself. Measured on 2026-09-23.
echo     RESTING LONGER between reps is what makes the signal - not
echo     shutting the eyes longer.
echo     The ONLY thing you check live is that MARK is magenta.
echo.
echo  D. CONTRAST, one head-turn and one look-down
echo     Turn your head away, then look down. The gate line must go
echo     CLOSED and branch 2 must stop voting. No branch-2 wording in
echo     the voice either.
echo.
echo  E. YAWN, once, hand OFF your face
echo     YAWN shows and the level goes to L1.
echo.
echo  WARNING  1. Turning your head CLOSES the gate and WIPES the 27 s
echo              warm-up. If WARMING appears again, that stretch is void -
echo              redo phase A.
echo.
echo           2. In phase C do NOT act tired. Branch 1 detects fatigue from
echo              the head-droop pattern, so letting your head sink as you
echo              close your eyes is exactly what CLOSES the gate and kills
echo              the warm-up. Close your eyes with your head held exactly
echo              where it was. Still eyes, still head - that is the whole
echo              experiment.
echo.

echo  ------------------------------------------------------------
echo  A real session cannot be repeated, so this run does NOT
echo  overwrite anything - it picks the first free name in runs\ :
set N=1
:findlog
if exist "runs\session%N%.csv" (
    set /a N+=1
    goto :findlog
)
set "LOG=runs\session%N%.csv"
echo.
echo       THIS SESSION WILL BE SAVED TO:  %LOG%
echo.
echo  Write that down. It is the file to hand over afterwards.
echo  (To force your own name: live_fuse.bat --log-probs x.csv)
echo  ------------------------------------------------------------
echo.
"D:\Anaconda3\envs\dms\python.exe" src\fuse.py --log-probs "%LOG%" %*

echo.
echo --- program exited. Your log is:  %LOG%
echo --- press a key to close ---
pause >nul
