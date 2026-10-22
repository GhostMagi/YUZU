#!/bin/bash
# THE BOARD'S OWN WIFI, for when there is no other. Not a command he
# types: `~/YUZU/face --boot` sets it up and a boot service runs it.
#
#   own_wifi.sh            at boot, as root: wait for a network the board
#                          knows, and make its own if none comes
#   own_wifi.sh --setup    from `face --boot`: make the network once,
#                          install the boot service, check the card can
#   own_wifi.sh --off      from `face --boot --off`: stop doing it
#   own_wifi.sh --show     its name and password, if it has one
#
# Ghost, Oct 22: "i wama be able to plug power in, and interact on
# something", and "if shtf and i have to live in a cave". He thought it
# already worked that way, and half of it did: the girls never touch the
# internet -- her mind, her voice, her ears and the wiki all live on this
# board. What his phone and the cube still needed was a NETWORK to reach
# the board on, and that was his router or his phone's hotspot. With
# neither in reach, the board now makes one.
#
# It is a FALLBACK, never the default. At home the board joins home, as
# it always has, and the cube finds it there. A hotspot that came up
# first at home would hide the board from everything that already
# works, so the board waits for the networks it knows before it makes
# its own.

set -u
CON=${YUZU_OWN_WIFI_CON:-yuzu-own-wifi}
UNIT=${YUZU_OWN_WIFI_UNIT:-/etc/systemd/system/yuzu-own-wifi.service}
# ${HOME:-} because systemd gives a root service no HOME at all, and
# under `set -u` a bare $HOME would end the boot check on line one.
KEEP=${YUZU_OWN_WIFI_KEEP:-${HOME:-/root}/.yuzu/own-wifi}
# Two minutes, because a router that lost power with the board takes
# about that long to come back, and making its own WiFi then would hide
# the board at home until the next restart.
WAIT=${YUZU_OWN_WIFI_WAIT:-120}
STEP=${YUZU_OWN_WIFI_STEP:-5}
PORT=${YUZU_FACE_PORT:-8081}
HERE="$(cd "$(dirname "$0")" && pwd)"

has_con() {
    nmcli -t -f NAME connection show 2>/dev/null | grep -qxF "$CON"
}

# ON A NETWORK means a phone could reach it: WiFi or a cable, connected.
# NOT the bridges that are always "connected" on a Jetson -- docker0,
# and l4tbr0 with the USB link under it, which is up whenever his serial
# cable is plugged in. Counting those would mean the board never makes
# its own WiFi while he is on the cable, which is exactly when he would
# set it up and check it.
on_a_network() {
    nmcli -t -f DEVICE,TYPE,STATE device status 2>/dev/null | awk -F: '
        $3 != "connected" { next }
        $1 ~ /^(usb|rndis|l4tbr|docker|veth|virbr|br-)/ { next }
        $2 == "wifi" || $2 == "ethernet" { found = 1 }
        END { exit !found }'
}

# The board's short name, or empty. The same refusal `face` makes:
# `localhost` is a legal name that means the device ASKING.
board_name() {
    local n; n=$(hostname -s 2>/dev/null)
    case "$n" in localhost|localhost.*|*[!A-Za-z0-9-]*|"") n="" ;; esac
    echo "$n"
}

# ---- at boot ---------------------------------------------------------------
boot() {
    if ! has_con; then
        echo "No $CON yet -- ~/YUZU/face --boot makes it."
        exit 0
    fi
    local waited=0
    while :; do
        if on_a_network; then
            echo "On a network it knows, so its own WiFi stays off."
            exit 0
        fi
        [ "$waited" -ge "$WAIT" ] && break
        sleep "$STEP"
        waited=$((waited + STEP))
    done
    echo "No network it knows after ${WAIT}s, so the board makes its own."
    nmcli radio wifi on >/dev/null 2>&1
    nmcli connection up "$CON"
}

# ---- the check, run DETACHED as root ---------------------------------------
# Switching the card into its own network drops whatever WiFi the board
# is on. Run from his terminal, a dropped session would kill the check
# halfway -- and leave the board on its own WiFi with home switched off.
# So it runs in its own session (setsid -f), puts home back itself, and
# leaves its verdict in a file.
try_it() {
    local prev="$1" out="$2" said ok=no
    if said=$(nmcli connection up "$CON" 2>&1); then
        ok=yes
        sleep 3
    fi
    nmcli connection down "$CON" >/dev/null 2>&1
    if [ -n "$prev" ]; then
        nmcli connection up uuid "$prev" >/dev/null 2>&1
    fi
    printf '%s\n%s\n' "$ok" "$said" > "$out.part" && mv -f "$out.part" "$out"
}

# ---- once, from face --boot ------------------------------------------------
setup() {
    if ! command -v nmcli >/dev/null 2>&1; then
        echo "  No NetworkManager on this board, so no WiFi of its own."
        return 0
    fi
    if ! nmcli -t -f TYPE device status 2>/dev/null | grep -qx wifi; then
        echo "  No WiFi card on this board, so no WiFi of its own."
        return 0
    fi
    local name pass said
    if ! has_con; then
        name=$(board_name)
        [ -n "$name" ] || name=yuzu-board
        # MADE ON THE BOARD, never written in the repo. Twelve letters and
        # digits with the look-alikes (0 o 1 l i) left out, in threes
        # of four. He types it once and his phone remembers it.
        pass=$(LC_ALL=C tr -dc 'abcdefghjkmnpqrstuvwxyz23456789' </dev/urandom \
               | head -c 12 | sed 's/..../&-/g; s/-$//')
        # 2.4 GHz (`band bg`) because the cube hears nothing else. WPA2
        # with CCMP only, because some phones refuse a hotspot that also
        # offers the old TKIP. `shared` makes the board the network's
        # router at 10.42.0.1, handing out addresses itself.
        # autoconnect no: only the boot check ever switches it on.
        if ! said=$(sudo nmcli connection add type wifi ifname '*' \
                    con-name "$CON" autoconnect no ssid "$name" \
                    802-11-wireless.mode ap 802-11-wireless.band bg \
                    ipv4.method shared ipv6.method ignore \
                    wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn \
                    wifi-sec.pairwise ccmp wifi-sec.group ccmp \
                    wifi-sec.psk "$pass" 2>&1); then
            echo "  COULD NOT MAKE ITS OWN WIFI. NetworkManager said:"
            printf '%s\n' "$said" | head -3 | sed 's/^/    /'
            return 1
        fi
    fi
    # What NetworkManager HAS is the truth, whatever this run made: a
    # second `face --boot` must never hand him a new password for a
    # network that still has the old one.
    name=$(nmcli -e no -g 802-11-wireless.ssid connection show id "$CON" 2>/dev/null)
    pass=$(sudo nmcli -e no -s -g 802-11-wireless-security.psk \
           connection show id "$CON" 2>/dev/null)
    local checked=""
    grep -qx 'checked: yes' "$KEEP" 2>/dev/null && checked=yes
    mkdir -p "$(dirname "$KEEP")"
    ( umask 077
      printf 'name: %s\npassword: %s\n' "$name" "$pass" > "$KEEP"
      [ -n "$checked" ] && echo "checked: yes" >> "$KEEP" )

    # Type=simple, NOT oneshot: a oneshot holds the boot for its two
    # minutes, and the desktop with it.
    sudo tee "$UNIT" >/dev/null <<UNITFILE
[Unit]
Description=YUZU: the board's own WiFi, when no other is in reach
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=simple
ExecStart=/bin/bash $HERE/own_wifi.sh

[Install]
WantedBy=multi-user.target
UNITFILE
    sudo systemctl daemon-reload >/dev/null 2>&1
    sudo systemctl enable yuzu-own-wifi.service >/dev/null 2>&1

    # ONE CHECK THAT THE CARD CAN DO IT, the first time only. Whether his
    # Orin's WiFi card will host a network is not knowable from here,
    # and the one place NOT to find out is the place he needs it.
    if [ -z "$checked" ] && [ "${YUZU_OWN_WIFI_TRY:-1}" != 0 ]; then
        echo "  Checking the board can make its own WiFi."
        echo "  Your WiFi drops for about 20 seconds..."
        local prev box result i
        prev=$(nmcli -t -f UUID,TYPE connection show --active 2>/dev/null \
               | awk -F: '$2=="802-11-wireless" {print $1; exit}')
        # A folder of HIS for root to write the verdict into: a root file
        # left loose in /tmp is one he could not delete afterwards.
        box=$(mktemp -d)
        result="$box/verdict"
        sudo setsid -f /bin/bash "$HERE/own_wifi.sh" --try "$prev" "$result" \
            </dev/null >/dev/null 2>&1
        for ((i = 0; i < 120; i++)); do
            [ -s "$result" ] && break
            sleep 1
        done
        if [ "$(head -1 "$result" 2>/dev/null)" = yes ]; then
            echo "  WORKS. Its own WiFi came up, and it is back on yours."
            ( umask 077; echo "checked: yes" >> "$KEEP" )
        elif [ -s "$result" ]; then
            echo "  THIS BOARD'S WIFI CARD WOULD NOT MAKE ITS OWN NETWORK."
            echo "  What it said:"
            sed -n '2,4p' "$result" | sed 's/^/    /'
            echo "  Your phone's hotspot still works away from home."
        else
            echo "  The check did not finish. Run ~/YUZU/face --boot again."
        fi
        rm -rf "$box"
        # Back on home before anyone prints an address.
        for ((i = 0; i < 30; i++)); do
            on_a_network && break
            sleep 1
        done
    fi
}

# ---- what face --status and face --boot print ------------------------------
show() {
    [ -r "$KEEP" ] || return 0
    local name pass host
    name=$(sed -n 's/^name: //p' "$KEEP")
    pass=$(sed -n 's/^password: //p' "$KEEP")
    [ -n "$name" ] || return 0
    host=$(board_name)
    echo "  NO WIFI AROUND? Two minutes after power on, the board makes"
    echo "  its own. Join it on your phone (or the cube) as:"
    echo "      $name   password: $pass"
    echo "  then open  http://10.42.0.1:$PORT/"
    [ -n "$host" ] && echo "         or  http://$host.local:$PORT/"
    echo "  If your phone says it has no internet, tap to stay connected."
    return 0
}

off() {
    sudo systemctl disable yuzu-own-wifi.service >/dev/null 2>&1
    sudo rm -f "$UNIT"
    sudo systemctl daemon-reload >/dev/null 2>&1
    echo "  It will no longer make its own WiFi at boot."
}

case "${1:-}" in
    --setup) setup ;;
    --off)   off ;;
    --show)  show ;;
    --try)   try_it "${2:-}" "${3:?}" ;;
    *)       boot ;;
esac
