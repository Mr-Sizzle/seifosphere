#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# seifosphere_sync.sh
# Exports new iMessage threads to the Seifosphere Archive intake folder.
# Runs daily via launchd. New files appear in the dashboard's New Messages tab.
#
# Install: see README at bottom of this file
# ─────────────────────────────────────────────────────────────────────────────

# ── Config ────────────────────────────────────────────────────────────────────
ARCHIVE_DIR="/Users/sizzle/imessage_export_IPHONE"
INTAKE_DIR="$HOME/Downloads"
EXPORT_TMP="$HOME/.seifosphere_tmp_export"
LOG="$ARCHIVE_DIR/sync.log"
EXPORTER="/opt/homebrew/bin/imessage-exporter"

# ── Logging ───────────────────────────────────────────────────────────────────
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}

log "━━━ Seifosphere sync started ━━━"

# ── Check exporter exists ─────────────────────────────────────────────────────
if [ ! -f "$EXPORTER" ]; then
  # Try alternate Homebrew path (Intel Mac)
  EXPORTER="/usr/local/bin/imessage-exporter"
fi
if [ ! -f "$EXPORTER" ]; then
  log "ERROR: imessage-exporter not found. Run: brew install imessage-exporter"
  exit 1
fi

# ── Export all threads to temp folder ─────────────────────────────────────────
rm -rf "$EXPORT_TMP"
mkdir -p "$EXPORT_TMP"

log "Running imessage-exporter..."
"$EXPORTER" -f html -o "$EXPORT_TMP" >> "$LOG" 2>&1

if [ $? -ne 0 ]; then
  log "ERROR: imessage-exporter failed"
  exit 1
fi

# ── Find files already in archive (to skip them) ──────────────────────────────
# Build a list of all HTML filenames already categorized
EXISTING=$(find "$ARCHIVE_DIR" -name "*.html" ! -path "*tmp*" -exec basename {} \; | sort)

# ── Copy only NEW files to Downloads intake ───────────────────────────────────
NEW_COUNT=0
for f in "$EXPORT_TMP"/*.html; do
  fname=$(basename "$f")
  
  # Skip orphaned.html — it's a catch-all with no useful content
  if [ "$fname" = "orphaned.html" ]; then
    continue
  fi

  # Check if this file already exists anywhere in the archive
  if echo "$EXISTING" | grep -qF "$fname"; then
    continue
  fi

  # Also skip if already sitting in Downloads waiting to be processed
  if [ -f "$INTAKE_DIR/$fname" ]; then
    continue
  fi

  # It's new — copy to Downloads for intake
  cp "$f" "$INTAKE_DIR/$fname"
  log "New file: $fname"
  NEW_COUNT=$((NEW_COUNT + 1))
done

log "Done. $NEW_COUNT new file(s) added to intake."
log "━━━ Sync complete ━━━"

# Clean up temp
rm -rf "$EXPORT_TMP"

exit 0

# ─────────────────────────────────────────────────────────────────────────────
# INSTALL INSTRUCTIONS
# ─────────────────────────────────────────────────────────────────────────────
#
# 1. Copy this script to your archive folder:
#    cp ~/Downloads/seifosphere_sync.sh /Users/sizzle/imessage_export_IPHONE/seifosphere_sync.sh
#
# 2. Make it executable:
#    chmod +x /Users/sizzle/imessage_export_IPHONE/seifosphere_sync.sh
#
# 3. Install the launch agent (runs daily at 8am):
#    cp ~/Downloads/com.seifosphere.sync.plist ~/Library/LaunchAgents/
#    launchctl load ~/Library/LaunchAgents/com.seifosphere.sync.plist
#
# 4. To run manually anytime:
#    /Users/sizzle/imessage_export_IPHONE/seifosphere_sync.sh
#
# 5. To check the log:
#    tail -50 /Users/sizzle/imessage_export_IPHONE/sync.log
#
# ─────────────────────────────────────────────────────────────────────────────
