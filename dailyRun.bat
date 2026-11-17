@echo off
:: Navigate to your script directory
cd /d "C:\Users\ND\Downloads\Badminton"

:: Configuration Environment Variables
set "ASPIRE_EMAIL=email"
set "ASPIRE_PASS=your passeord"
:: set as false while testing
set "HEADLESS=true"
set "DAYS_IN_ADVANCE=10"
set "MAX_START_HOUR=21"
set "SLOT_OFFSET_MINUTES=59"

:: priroity order
set "PRIORITY_ORDER=19:30+20:30, 20:00+21:00, 19:00+20:00, 18:30+19:30, 20:30+SPLIT, 17:30+18:30, 17:00+18:00"

:: Optional Day-Specific Priorities (uncomment and edit if needed)
set "DAY_PRIORITIES_JSON={"Saturday": "08:30+09:30, 08:00+09:00", "Sunday": "18:00+19:00"}"

echo Starting Aspire Booking Script...
py dailyBooking.py >> dailyBooking.log 2>&1

echo [%DATE% %TIME%] Execution Finished. >> dailyBooking.log
echo ======================================== >> dailyBooking.log