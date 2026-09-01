# Start here if you're on your phone

No terminal. No commands. Just tap Run.

---

## 1. Get the file

In your phone's browser, open the repo, find **`yuzu_doctor.py`**, and
hit the download button. It lands in your Downloads folder.

That's the only file you need. It works completely on its own.

## 2. Open it in Pydroid

Pydroid → the folder icon → Downloads → `yuzu_doctor.py`

## 3. Press the ▶ button

That's it. It'll take up to about half a minute — it's looking around
your storage for your model file.

## 4. Screenshot the bottom

The last section is titled **SUMMARY — screenshot from here down**.
Send that to Claude.

---

## What it's checking

- Whether it's running on your phone or a computer
- Which Yuzu files are in the folder with it (none is fine)
- Whether Yuzu's action parser still works — it runs a real test reply
  through it and shows you what she'd say and what she'd do
- Whether it can find your `.gguf` model file, and if so whether the
  model has a working **chat template**

That last one is the one that matters. If a model's chat template is
missing or broken, it still loads and still talks — it just ignores
Yuzu's personality completely and sounds like a stock assistant. That
looks exactly like a bad prompt and isn't, and you'd never guess it
without checking.

## If it says it can't find your model

That's normal and nothing is broken. Android keeps each app's downloads
private, so if PocketPal downloaded the model itself, Pydroid genuinely
cannot see into PocketPal's folder. Android won't let it.

**Easiest thing:** open PocketPal → Models → tap your model →
screenshot that screen. The model's name and quant is most of what's
useful anyway.

**If you want the full check:** download the same `.gguf` again using
your phone's *browser* instead of inside PocketPal. Browser downloads
go to your shared Downloads folder, where the script can read them.
Then press Run again. (It's the same file twice, so delete one after.)

## If something goes wrong

The script is written not to throw a wall of red text at you. If it
does hit a problem it says so in plain English and tells you to
screenshot it. That's a bug in the script, not something you did.
