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
