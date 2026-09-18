# Flykeeper

A personal Drosophila breeding manager for tracking individual containers, planning fly work, and keeping important manipulation times on your calendar. It runs locally on your computer and uses an English interface.

> **Active development:** Flykeeper is experimental. Expect bugs, incomplete features, and changes to existing behavior. Keep regular backups and check experimental timings against your own protocol before relying on reminders.

## Install on Windows

You need **Python 3.13 or newer** with the Windows `py` launcher, **Node.js 22.13 or newer** with `npm`, and an internet connection for installation. The supplied installation and launch scripts are for Windows.

1. Download this repository using **Code → Download ZIP** on GitHub and extract it, or clone it with Git:

   ```powershell
   git clone https://github.com/Skxsmy/Fly-control-system.git
   ```

2. Open PowerShell in the extracted or cloned project folder—the folder containing `Setup-Flykeeper.ps1`. Install dependencies and build the app:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup-Flykeeper.ps1
   ```

   Wait for **Setup complete**. This creates a Python environment, installs the required packages, and builds the interface.

3. Double-click **Start-Flykeeper.cmd**. Keep its console open while using the app. Your browser opens automatically, usually at [http://127.0.0.1:48173](http://127.0.0.1:48173).

Ordinary stock management works offline after installation. AI assistance is optional and requires a configured cloud API or a running local model server.

| Action | How |
| --- | --- |
| Run without a console window | Double-click `Start-Flykeeper-Background.cmd`. |
| Stop the app | Double-click `Stop-Flykeeper.cmd`, or use **Protocols & settings → Shut down Flykeeper**. Closing a browser tab does not stop it. |
| Change the port | Edit `port` in `flykeeper.config.json`, then restart. If a port is occupied, the launcher selects a nearby free one. |
| Diagnose startup problems | Use `Start-Flykeeper.cmd` to read errors; background logs are in `.runtime/server.log`. If `py` or `npm` is not found, check the prerequisite installation and reopen PowerShell. |

## Get started

1. Open **Protocols & settings** and set your laboratory time zone and weekly working hours. Add holidays, leave, or other unavailable dates in **Calendar**.
2. Select **New container**. Enter its type, purpose, genotype, and setup date. To enter an existing culture, expand **Initial state** and set its current stage, parent status, and transfer count.
3. Open the container to record transfers, observations, collections, parent removal, or temperature changes.
4. Check **Today** for due, overdue, and upcoming work. Add custom reminders or reschedule individual tasks as needed.

The setup date is **D0**, and each midnight starts the next Day: a culture set up at 21:00 is D1 three hours later. Exact operation times, egg ages, and temperature-adjusted developmental estimates remain separate. Setup time is optional when first adding vials and bottles. Transfers, renewal, egg-laying containers, and Petri dishes require a time.

Use **Transfer parents** to continue with the same adults; the new container tracks their transfer count and next transfer time. Use **Renew stock culture** to start a fresh stock vial or bottle with the inherited genotype and transfer count **0**. This completes the renewal reminder and discards the source container while keeping its records.

**Today's work** includes reminders scheduled for today and ongoing stock renewal. **Needs attention** shows unfinished reminders from previous days or collection windows that have already ended.

## Features

| Area | What you can do |
| --- | --- |
| Containers and stocks | Keep an independent record for each vial, bottle, egg-laying container, or Petri dish. Search and group by genotype; track source containers, parent transfers, notes, and observed stages. |
| Breeding workflows | Maintain stocks, collect virgin females, or set up genetic crosses for F1 selection/scoring, virgins, or third-instar larvae. Crosses record separate parental genotypes and a target outcome. |
| Calendar and reminders | Set weekly or partial-day availability, holidays, and leave. Add, complete, skip, disable, or reschedule reminders. Rescheduling preserves the task's identity and can keep its original duration. |
| Temperature and setup planning | Record actual 18°C/25°C moves, view adjusted developmental estimates, and request setup-date or cooling suggestions around your availability. Accepting a cooling plan creates reminders; record the actual moves separately. |
| Timed egg work | Create an egg-laying container from an existing vial/bottle, selecting parents or offspring and a known adult genotype. Record laying windows and egg collections; use aliquots for Petri dishes, dissection, imaging, or other work. |
| Hourly incubation | Track an egg-age range and an editable first-instar estimate from the original laying window. Record observed first instar, dissection, and imaging. |
| Injection preparation | Collect adults from a vial/bottle into a separately numbered preparation bottle, transfer them to a linked cage, and run repeated 30-minute embryo collections. |
| Corrections | Delete an operation from **Activity** and undo its changes, or delete only the record while keeping current state and later work. Independent entries can be removed in any order. The preview explains retained data and any clock changes. |
| Cleanup | **End culture** and **Discard culture** retain history. **Delete container permanently** removes a mistaken container after a preview and backup, releases its label, and is blocked by dependent records. |

Default schedules are editable laboratory presets:

Changing protocol values in **Protocols & settings** updates the affected reminders in existing active and planned cultures, including rescheduled reminders. Completed history is retained. Unchanged culture-specific parameters remain intact.

- **Virgin collection:** one culture day, initially D10, with three windows: **09:00–11:00**, **15:00–15:30**, and **19:00–21:00**.
- **Third-instar collection:** **25°C-equivalent D5** by default, adjusted by the vial/bottle's temperature history.
- **Parent transfer:** optional **D3**, with up to two transfers.
- **Stock renewal:** starts on calendar **D10** and stays in Today's work until renewed.
- **Culture checks:** initially D6, including a tissue reminder for bottles.
- **Petri-dish incubation:** an initial **24–30-hour** estimate applied to the full laying window.

Cooling delays developmental reminders; recording a return to 25°C brings them forward relative to continued cooling, retaining the delay already accumulated. Parent transfer/removal, stock renewal, and manually rescheduled reminders keep their calendar times. Hourly egg protocols do not use this temperature adjustment. Timing predictions are estimates; check suitability for your genotype and experimental conditions. Reminders appear in the app; there are no closed-app notifications.

## Injection preparation

Open an active vial/bottle and choose **Injection preparation**. The source must be at 25°C; cooling is unavailable during this workflow. Confirm the collected flies' genotype, especially when the source is a cross.

1. Stock renewal is cancelled and **Collect flies** appears for D10–12. The target is at least **200 females**, about **50–67 males**, with female:male **3:1–4:1**. Record the actual counts when collection is complete.
2. The linked **IB** bottle waits for those flies and yeast. Completing collection records the actual start time, makes that date D0, and cancels the other collection reminders.
3. At midnight on preparation **D4**, a linked **C** cage with a yeast plate appears as planned. Confirm **Transfer all flies to cage** to activate it and discard the IB bottle. The cage inherits the bottle's D0.
4. **Renew yeast plate** appears from midnight on **D5**. Embryo collection is due **30 minutes after the actual replacement**. On collection, choose to immediately renew the plate and start another 30-minute interval, or finish.

Source D10–12 retains the effect of temperature history recorded before preparation. D4/D5 reminders also show their original target time. Finishing embryo collection stops the reminders; it does not automatically discard the cage.

## Optional AI assistant

1. Open **Protocols & settings → AI connection** and choose **Cloud API** or **Local model**.
2. Enter an OpenAI-compatible API **Base URL** and, if required, an API key. Include `/v1` if your provider requires it; do not enter the full `/chat/completions` route. Cloud connections require HTTPS; local servers must run on this computer.
3. Click **Fetch models**, select a model, or enter its ID manually. Choose **Save and test** to check that the model can respond.
4. Open **Assistant**, choose whether to include workspace data, and ask a question or discuss an L1/L3 dissection schedule. You can select individual containers and their sources as context.

With a cloud connection, the selected workspace records—including genotypes and notes—and the conversation are sent to that provider. AI replies are advisory: the assistant cannot modify records or apply a plan. Conversations are lost on page reload. A workflow editor and automatic experimental-plan execution are not yet implemented. Injection preparation is available; the subsequent transgenesis workflow is not implemented.

## Back up and restore

Your laboratory records are stored in `data/flykeeper.db`. Use **Protocols & settings → Backup & restore → Download backup** to export a consistent snapshot. It includes containers, egg batches, activities, temperature history, reminders, calendar settings, and plans. AI connection profiles and keys are excluded.

To restore:

1. Choose **Import backup**, select a Flykeeper database file, and click **Check backup**.
2. Review the record counts, type `RESTORE`, and select **Restore workspace**.

**Restore replaces the current workspace; it does not merge records.** A recovery backup is saved first and can be downloaded or found in `backups/`. AI connection settings remain unchanged. Keep exported copies outside the project folder; sync backup files rather than the live database.

## Update

Download a backup, stop Flykeeper, then update the source with `git pull` or extract the new version into a separate folder. Run `Setup-Flykeeper.ps1` again and restart. Keep your existing `data/`, `backups/`, and configuration files; when switching to a separate installation, use **Import backup** to transfer the laboratory workspace and configure AI again.

## Development documentation

See [HANDOFF.md](HANDOFF.md) for the architecture, development commands, implementation boundaries, and next-work context. [AGENTS.md](AGENTS.md) contains the project conventions for coding assistants.
