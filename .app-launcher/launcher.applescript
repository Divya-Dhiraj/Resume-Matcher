-- Resume-Matcher launcher — single icon, opens the browser reliably.

property launcherScript : "/Users/divya/Projects/Resume-Matcher/.app-launcher/resume-matcher-launcher.sh"
property appUrl : "http://localhost:3000"

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

on openBrowser()
	set bid to defaultBrowserBundle()
	try
		if bid is not "" then
			do shell script "open -a " & quoted form of bid & " " & quoted form of appUrl
			delay 0.3
			tell application id bid to activate
		else
			do shell script "open " & quoted form of appUrl
		end if
	end try
end openBrowser

on run
	-- Check current state
	set statusLine to "unknown"
	try
		set statusLine to do shell script "bash " & quoted form of launcherScript & " status 2>&1"
	end try

	if statusLine is "up" then
		-- Already running: just open the browser
		openBrowser()
		return
	end if

	-- Not up — start everything in the background so the applet doesn't hang
	display notification "Starting — Docker + dev stack…" with title "Resume Matcher"

	-- Launch start in background, then poll for readiness
	do shell script "bash " & quoted form of launcherScript & " start >> ~/Library/Logs/resume-matcher-launcher.log 2>&1 &"

	-- Poll for up to 5 minutes
	set maxWait to 300
	set waited to 0
	repeat while waited < maxWait
		delay 5
		set waited to waited + 5
		try
			set pollStatus to do shell script "bash " & quoted form of launcherScript & " status 2>&1"
			if pollStatus is "up" then
				display notification "Ready!" with title "Resume Matcher"
				openBrowser()
				return
			end if
		end try
	end repeat

	display dialog "Resume Matcher did not come up in 5 minutes." & return & return & "Check: ~/Library/Logs/resume-matcher-launcher.log" buttons {"OK"} default button "OK" with title "Resume Matcher" with icon caution
end run
