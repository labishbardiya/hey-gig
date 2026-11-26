# Hey GIG

Hey GIG is a university glasses prototype with a Raspberry Pi capture unit, a Mac glasses display, a Samsung tablet companion, and a backend that will move from the Mac to the lab RTX PC.

| Milestone | Demonstration |
| --- | --- |
| 1. Hardware and live feeds | See both physical cameras on the Mac, hear a test phrase through the Pi-paired earbuds, verify microphone input, and complete a 20-minute bench run. |
| 2. Conversational assistant | Speak a question, interrupt the answer, scan several pages into a searchable PDF, review it on the tablet, and approve an external action. Add two-way English/Hindi translation and test the privacy switch across capture devices. |
| 3. Integrations and lab deployment | Move inference to the RTX PC, add public research with god-scrape, Google services, messaging, CALL-E, routines, and the remaining selected features. Demonstrate recovery when the network or a provider fails. |

## Part one

### 1. Identify the board and both cameras

In a terminal on the Pi, or in its SSH session, run:

```sh
hostname
vcgencmd measure_temp
rpicam-hello --list-cameras
v4l2-ctl --list-devices
```

Look for a USB camera with a capture node (the tested setup used /dev/video0) and a CSI sensor such as imx219. Device numbers may change on reboot. Codec and ISP devices are internal components. For a missing USB camera, plug it directly into the Pi and repeat the device listing.

### 2. Check the USB camera independently

On the Pi, close any other camera viewer and run:

```sh
timeout 15s ffmpeg -hide_banner -nostdin -f v4l2 -framerate 15 -video_size 640x480 -i /dev/video0 -frames:v 30 -f null -
```

Look for a final frame count of 30. This test discards the frames.

### 3. Open the USB feed on the Mac

The USB sender uses the FFmpeg capture mode from step 2. In a fresh **Mac Terminal** window, change into this repository and run the following, substituting your current Pi SSH login:

```sh
python3 -m gig.preview gig@PI_ADDRESS --camera usb
```

Enter the Pi password in that terminal when SSH asks. Open the local URL printed by the launcher, paste the session token into the viewer, and choose **Connect**. Move a sheet of paper in front of the USB camera. The **reading** image should move. Press Ctrl+C in the launcher terminal when finished.

The launcher needs Python 3.10+ and OpenSSH on the Mac. It sends the camera code over one SSH session and forwards the Pi's loopback port to the local viewer. Frames stay in memory and expire after five seconds. **Stop preview** hides the browser image. **Ctrl+C in the launcher** ends capture. A lost SSH session stops the senders once the Pi detects closure. If the remote port is already used, choose a different one with `--remote-port 18881`.

### 4. Test the ribbon camera by itself

If the sensor is missing, shut down the Pi, wait for shutdown to finish, and disconnect power before touching the ribbon. Connect the camera directly to its CSI camera port with a short known-good ribbon, fully insert both ends, latch them, then restore power. Reconnect over SSH and repeat `rpicam-hello --list-cameras`. Once the sensor appears, run:

```sh
timeout -k 2s 12s rpicam-still --nopreview -t 1500 -o /tmp/gig-scene-check-$$.jpg && file /tmp/gig-scene-check-$$.jpg
```

Expect a new JPEG with image dimensions. This step saves a test photo under /tmp on the Pi. A timeout or missing sensor means the CSI path still needs diagnosis. Check the exact board, connector and ribbon before changing boot settings. Test one hardware change at a time.

### 5. See both cameras together

The CSI sender uses `rpicam-vid` and FFmpeg. Stop any previous preview, then run the Mac launcher with `--camera both`. Cover one lens at a time. Confirm that the USB camera changes **reading**, and the ribbon camera changes **scene**. Compare the reading image with the printed page at your intended working distance.

### 6. Test the wearer’s earbuds

Pair the earbuds through the Pi's desktop Bluetooth menu. In its Sound settings select the headset profile supporting input and output. Use `wpctl status` as the logged-in desktop user to verify the active input and output are the Bluetooth headset. With the volume low, play a short sound on the Pi. Record and replay a short spoken phrase with the desktop recorder or PipeWire commands:

```sh
pw-record /tmp/gig-earbud-check.wav
# Speak, press Ctrl+C, then run the next command.
pw-play /tmp/gig-earbud-check.wav
```

Confirm the wearer hears the phrase and that the selected input is the earbud microphone. This is a deliberate short test recording.

### 7. Run the bench test

Run both previews for 20 minutes. Keep a second Pi terminal open and use `watch -n 5 'vcgencmd measure_temp && vcgencmd get_throttled'`. Record the initial and final temperature, highest observed temperature, initial/final throttling flags, feed interruptions, and audio dropouts. Check the microphone and playback while both feeds run. Stop the launcher and confirm the camera devices can be opened again. Stop early if sustained heat or current throttling returns. Full electrical privacy-switch verification belongs to milestone two.

## Searchable PDF export

Start the Mac preview and connect to the reading camera. Hold each page steady in
view and choose **Add reading frame**. Review the thumbnails and remove any
unwanted captures. Choose **Save searchable PDF** to download one PDF with up to
20 pages in capture order. The browser saves it using its download settings.

The Mac receiver needs `tesseract` with the English (`eng`) language data and
`qpdf` on its PATH. The Homebrew OCRmyPDF installation supplies both commands.
Tesseract recognizes the camera JPEGs directly and adds a text layer to each
page. qpdf merges the pages. OCR uses local temporary files during export.
The capture queue lasts for the lifetime of the browser tab.

Use a sharp, well-lit, upright image of printed text. The current mode expects a
block of English text. Searchability and recognition accuracy depend on the scan.

## Local verification

```sh
python3 -m unittest discover -s tests -v
```

## Local library and share approvals

PDF exports also enter the Library. Download a copy there or select **Draft
share**, enter the intended recipient, then select **Approve** or **Deny** in
Approvals. Activity records the export and each decision. Approved drafts are
shown as delivery pending. Delivery requires a separately configured provider.

The Mac stores PDFs, recipients, and activity in
`~/.local/share/hey-gig/library.sqlite3`. Set `GIG_LIBRARY` to a different
SQLite file to keep demo data separate. Use a dedicated file for scans you want
to keep separate from your regular library.

## Automatic capture and structured text

On the Mac, create a scan environment with Python 3.12 and OpenCV:

```sh
uv venv --python 3.12 .venv-scan
uv pip install --python .venv-scan/bin/python -r requirements-scan.txt
.venv-scan/bin/python -m gig.preview gig@172.16.54.205 --camera usb --device /dev/video0
```

Enable **Auto-capture**, frame all four corners of a printed sheet against a
contrasting background, and hold it steady. The HUD checks sharpness and
corner movement, straightens the page, and suppresses visually similar
captures. If two pages look alike or the corners are difficult to detect,
use **Add page**. Remove a captured page to allow it to be captured again.

**Extract text** displays recognized English lines in page order. **Save
extraction JSON** downloads the lines and words, each word's confidence and
bounding box in processed OCR image pixels. Text extraction straightens and enhances manual and automatic captures. **Save searchable PDF** still exports the
reviewed page order. See [extraction trade-offs and Mac results](ARCHITECTURE.md)
for the comparison with PaddleOCR.

## USB tablet companion

Build with Android SDK Platform 34, Build Tools 34.0.0 and JDK 17:

```sh
./tablet/build.sh
adb install -r tablet/build/hey-gig.apk
adb reverse tcp:18765 tcp:18765
```

Use `--port 18765` when starting `gig.preview` on the Mac, then enter that
session's token in the tablet app. Both screens then use the same receiver
and library. For library-only use, start `gig.server --port 18765` with
`GIG_TOKEN` set. The app uses USB loopback and requires the Mac server.

The companion shows saved documents, share approvals, activity, reminders and
routines. Reminders become due in the running backend and appear in Activity.
The privacy switch clears the Mac receiver frame cache and releases the Pi camera when using the SSH preview launcher. The software control does not mute unrelated Pi audio.

## Local assistant

Start the Pi preview with `--identity-file` so the Mac can open an SSH
audio session. On the Mac install `whisper-cpp` and `poppler` with Homebrew.
Place the whisper.cpp English base model at
`~/.local/share/hey-gig/models/ggml-base.en.bin`, or set
`GIG_WHISPER_MODEL` to an alternate local model path. Speech replies use
macOS speech synthesis. Select a Galaxy Buds headset profile with both
input and output available in PipeWire on the Pi.

Open **Assistant** on the Mac or tablet. **Talk for 5 seconds** records
through the Pi buds, then transcribes and responds locally. The same
commands are available from the text field. Try these examples:

- Save a two-page scan with distinct terms, then ask
  “What does the scan say about lighthouse?” The assistant quotes a
  matching line from the most recent searchable PDF and names the page.
- Say “Remind me to charge the camera in 10 minutes.” Check Reminders
  for the saved entry. For a request without a supported interval, use
  **Choose reminder time** to complete the prefilled form.
- Save an **Open scanner** routine named “Scan desk.” Say “Run Scan desk”
  and check that Scanner opens and Activity logs the run.
- Pause camera capture. The Assistant disables Talk, the backend rejects
  new voice requests, and the Pi checks privacy during capture and playback.

This is an English push-to-talk prototype with keyword-based document
answers and a small set of local commands. Physical audio device
availability is checked on each request.

## CALL-E outbound calls

Open **Calls** on the Mac or tablet. Choose **Demo**, supply a recipient
label and a task, then select **Draft for approval**. Approve the demo in
Call history and watch it advance through accepted, in progress, and
completed. The final card includes a sample summary and transcript.
Denying a draft leaves it unsubmitted. Activity records status changes.

Live mode requires a key from the [CALL-E dashboard](https://dashboard.heycall-e.com/account/api-keys).
Set `CALLE_API_KEY` in the Mac launcher environment before starting
`gig.preview` or `gig.server`. Keep the key out of the tablet, chat, and Git.
Pick **Live CALL-E**, enter one authorized international number, review the
task and destination, and confirm **Approve and place call**. Calls V2 can
charge credits. Start with a consenting test recipient.

The Mac submits a single immediate outbound call using an idempotency key
stored with its approved draft. It polls using the returned CALL-E resource
ID and resumes polling that ID after a restart. The separate billing ID
appears when CALL-E reports it. If submission is unconfirmed, check the
provider dashboard before creating another draft. Pre-dial cancellation is
best effort and does not hang up an active call. Call instructions, status,
and returned summaries and transcripts are kept in the existing local
SQLite library. The feature covers outbound Calls V2.

## Software privacy

**Pause camera and mic** stops the Pi camera and ends Hey GIG audio sessions
that overlap the pause. The receiver discards buffered frames and the HUD
clears its unsaved scan pages when it sees the privacy change. The paused
state persists across Mac backend restarts. Saved library documents and call
history remain available. Voice and camera resume after the user selects
**Resume camera and mic**. The control operates Hey GIG's capture processes.

To enable live CALL-E on the Mac without putting the key in the launch command,
save it in `~/.local/share/hey-gig/calle-api-key` with owner-only permissions
(`chmod 600`). The backend reads it at startup. An explicit environment key
takes precedence. After restart, the presence of **Live CALL-E** confirms that
the backend loaded a key. Provider authentication is confirmed separately.
A typed or spoken instruction such as “Draft a call to Campus Lab to ask
about opening hours” prefills the Calls form. Choose the call mode and review
the draft before the separate approval step.

To revise a scheduled reminder, choose **Edit** in Reminders, update the
text or due date, and select **Save changes**.

## Local translation and tools

**Translate** alternates five-second turns. On the USB-connected tablet,
**Speak English on Buds** captures the Pi headset and plays the Hindi reply
on the tablet. **Speak Hindi on tablet** captures the tablet mic and sends
the English reply to the Buds. Both transcripts appear on screen. The
Android companion requests microphone permission at first use. Capture
stops when the privacy switch changes or the backend becomes unreachable.

The Mac needs whisper.cpp, FFmpeg and macOS speech synthesis with **Lekha**
available. The English ASR model is the existing `ggml-base.en.bin`.
Place `ggml-small-q5_1.bin` in the same models folder for Hindi input,
or set `GIG_MULTILINGUAL_MODEL` to a compatible local model. Start the
Qwen3 1.7B GGUF translation service on the Mac:

```sh
llama-server -m ~/.local/share/hey-gig/models/Qwen3-1.7B-Q8_0.gguf \
  --host 127.0.0.1 --port 18767 -c 2048 -ngl 99 --jinja --reasoning off \
  --cors-origins localhost --no-cors-credentials
```

**Tools** supports visual questions about one live USB frame when a local
vision-capable llama.cpp server listens at port 18768. The tested setup
uses SmolVLM2‑500M Q8 and its matching multimodal projector. **Read a public
source** uses the installed God Scrape runtime and returns matching
excerpts from the supplied public HTML URL, with the source attached.

## Drive, messaging, and Maps

In **Library → Upload or share a scan**, pick a saved scan and destination,
then review the destination under **Approvals**. Drive and Telegram submit
once after approval. An unconfirmed submission requires checking the provider
before creating another draft.

- **Google Drive** uses an OAuth access token with the
  `https://www.googleapis.com/auth/drive.file` scope. Set
  `GIG_GOOGLE_DRIVE_TOKEN` or save it to
  `~/.local/share/hey-gig/google-drive-token` with mode 600. Enable the Drive
  API for the OAuth project. Replace the access token when it expires.
- **Telegram** uses `GIG_TELEGRAM_BOT_TOKEN` or the owner-only
  `~/.local/share/hey-gig/telegram-bot-token` file. Use a chat ID for a chat
  that has started the bot or a channel where the bot can post. The PDF
  goes directly to that chat after approval.
- **WhatsApp** requires a successful Drive upload for the same scan. Review
  the international number and link under Approvals, then open WhatsApp
  and send from there. The recipient needs access to the Drive file.

**Maps** creates a Google Maps directions link from the two places and travel
mode you enter. Link creation needs no key. For optional in-app distance and
duration estimates, enable Google Routes and set `GIG_GOOGLE_MAPS_KEY` on the
Mac before launching the backend. Tablet companion v0.3 opens approved
WhatsApp and Drive links and user-selected Maps links in an external app.

### Set up live provider credentials

From the repository on the Mac, run the matching command below and paste the
value into its hidden Terminal prompt. Keep credentials out of chat and Git.

```sh
python3 -m gig.provider_setup save drive
python3 -m gig.provider_setup save telegram
python3 -m gig.provider_setup save routes
```

**Drive.** In Google Cloud, enable the Google Drive API. Set up the OAuth
app's Branding and Audience. For an External app in Testing, add your Google
account as a test user. Under Clients create a Web application with authorized
redirect URI `https://developers.google.com/oauthplayground`. In the
[OAuth Playground](https://developers.google.com/oauthplayground/), open the
gear, enable **Use your own OAuth credentials**, and enter that client ID and
secret. Enter `https://www.googleapis.com/auth/drive.file` in Step 1 and
authorize. In Step 2 exchange the authorization code and save the **access
token** with the command above. Refresh it in the Playground and save the
replacement when it expires. Hey GIG does not use the client secret or refresh token.

**Telegram.** Open [@BotFather](https://t.me/BotFather), send `/newbot`,
and save the resulting token. Open the new bot from the intended private test
account, tap **Start**, and send a short message. Run:

```sh
python3 -m gig.provider_setup telegram-chats
```

Use the numeric ID beside the private test chat. Prefer a dedicated test bot
with no webhook so the command can read its recent updates.

**Routes.** Enable Routes API in a Cloud project with billing enabled. Under
APIs & Services → Credentials, create an API key and choose **Restrict key →
Routes API**. If this Mac has a stable public egress IP, also apply that
server IP restriction. Save the key with the Routes command. In the app, use
**Maps → Request distance and time with Routes API** to request an estimate.
