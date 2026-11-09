-- Resume-Matcher launcher — single icon, opens the browser reliably.

property launcherScript : "/Users/divya/Projects/Resume-Matcher/.app-launcher/resume-matcher-launcher.sh"
property appUrl : "http://localhost:3000"

-- Find the user's default HTTP browser bundle id so we can activate it at
-- the very end. If we don't do this, the applet's own `activate` call (or
-- a lingering notification) snaps focus back onto Resume Matcher after the
-- URL opens, and the user sees Finder/Resume Matcher frontmost instead of
-- the browser they wanted.
on defaultBrowserBundle()
	try
		return do shell script "python3 -c '
import plistlib, os
with open(os.path.expanduser(\"~/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist\"), \"rb\") as f:
    p = plistlib.load(f)
for h in p.get(\"LSHandlers\", []):
    if h.get(\"LSHandlerURLScheme\") == \"http\":
        print(h.get(\"LSHandlerRoleAll\", \"\"))
        break
'"
	on error
		return ""
	end try
end defaultBrowserBundle

on activateBrowser()
	set bid to defaultBrowserBundle()
	if bid is not "" then
		try
			do shell script "open -b " & quoted form of bid
		end try
	end if
end activateBrowser

on run
	set statusLine to do shell script "bash " & quoted form of launcherScript & " status"
	
	if statusLine is "up" then
		-- Already running: open the URL, then activate the browser so it
		-- actually comes to the front.
		do shell script "bash " & quoted form of launcherScript & " open"
		activateBrowser()
		return
	end if
	
	-- Not running: run the start pipeline with a generous timeout so Docker
	-- cold-boot doesn't trigger AppleScript's default 2-minute kill.
	display notification "Starting — Docker + dev stack…" with title "Resume Matcher"
	
	try
		with timeout of 600 seconds
			set result to do shell script "bash " & quoted form of launcherScript & " start"
		end timeout
	on error errMsg
		display dialog "Could not start Resume-Matcher." & return & return & errMsg & return & return & "Details: ~/Library/Logs/resume-matcher-launcher.log" buttons {"OK"} default button "OK" with title "Resume Matcher" with icon stop
		return
	end try
	
	if result contains "READY" then
		do shell script "bash " & quoted form of launcherScript & " open"
		activateBrowser()
	else
		display dialog "Start did not report READY." & return & return & result & return & return & "Details: ~/Library/Logs/resume-matcher-launcher.log" buttons {"OK"} default button "OK" with title "Resume Matcher" with icon caution
	end if
end run
