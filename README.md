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

The setup date is **D0**. Setup time is optional for vials and bottles; egg-laying containers and Petri dishes require a time.

Use **Transfer parents** to continue with the same adults; the new container tracks their transfer count and next transfer time. Use **Renew stock culture** to start a fresh stock vial or bottle with the inherited genotype and transfer count **0**. Creating it completes the source's renewal reminder.

## Features

| Area | What you can do |
| --- | --- |
| Containers and stocks | Keep an independent record for each vial, bottle, egg-laying container, or Petri dish. Search and group by genotype; track source containers, parent transfers, notes, and observed stages. |
| Breeding workflows | Maintain stocks, collect virgin females, or set up genetic crosses for F1 selection/scoring, virgins, or third-instar larvae. Crosses record separate parental genotypes and a target outcome. |
| Calendar and reminders | Set weekly or partial-day availability, holidays, and leave. Add, complete, skip, disable, or reschedule reminders. Rescheduling preserves the task's identity and can keep its original duration. |
| Temperature and setup planning | Record actual 18°C/25°C moves, view adjusted developmental estimates, and request setup-date or cooling suggestions around your availability. Accepting a cooling plan creates reminders; record the actual moves separately. |
| Timed egg work | Create an egg-laying container from an existing vial/bottle, selecting parents or offspring and a known adult genotype. Record laying windows and egg collections; use aliquots for Petri dishes, dissection, imaging, or other work. |
| Hourly incubation | Track an egg-age range and an editable first-instar estimate from the original laying window. Record observed first instar, dissection, and imaging. |
| Corrections | Delete an operation from **Activity** and undo its changes, or delete only the record while keeping current state and later work. Independent entries can be removed in any order. The preview explains retained data and any clock changes. |
| Cleanup | **End culture** and **Discard culture** retain history. **Delete container permanently** removes a mistaken container after a preview and backup, releases its label, and is blocked by dependent records. |

Default schedules are editable laboratory presets:

- **Virgin collection:** one culture day, initially D10, with three windows: **09:00–11:00**, **15:00–15:30**, and **19:00–21:00**.
- **Third-instar collection:** calendar **D5** by default.
- **Parent transfer:** optional **D3**, with up to two transfers. Stock renewal defaults to **11 days**.
- **Culture checks:** initially D6, including a tissue reminder for bottles.
- **Petri-dish incubation:** an initial **24–30-hour** estimate applied to the full laying window.

Timing predictions are estimates. Temperature adjustments apply to developmental forecasts; calendar-based tasks and hourly egg protocols have their own rules. Check suitability for your genotype and experimental conditions. Reminders appear in the app; there are no closed-app notifications.

## Optional AI assistant

1. Open **Protocols & settings → AI connection** and choose **Cloud API** or **Local model**.
2. Enter an OpenAI-compatible API **Base URL** and, if required, an API key. Include `/v1` if your provider requires it; do not enter the full `/chat/completions` route. Cloud connections require HTTPS; local servers must run on this computer.
3. Click **Fetch models**, select a model, or enter its ID manually. Choose **Save and test** to check that the model can respond.
4. Open **Assistant**, choose whether to include workspace data, and ask a question or discuss an L1/L3 dissection schedule. You can select individual containers and their sources as context.

With a cloud connection, the selected workspace records—including genotypes and notes—and the conversation are sent to that provider. AI replies are advisory: the assistant cannot modify records or apply a plan. Conversations are lost on page reload. A workflow editor and automatic experimental-plan execution are not yet implemented; transgenesis workflows are deferred.

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
