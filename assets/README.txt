THE SOURCE PACKS, kept on purpose.

ui/vpet/ holds the files the deck actually runs -- cropped, renamed and
committed. These zips are what they were cut from. A lossy step whose
input was thrown away can never be improved on, which this repo already
learned the hard way when a bad crop ate blink.png and only git had the
original.

    Pack 01 (free tier)   Soldier, Orc
    Pack 02 (free tier)   Demon_A, Blood Monster_A   <- Demon_A is live

WHAT IS IN ui/vpet/ AND HOW IT GOT THERE

    idle.png   <- Demon_A_Idle.png       6 cels
    walk.png   <- Demon_A_Walk.png       8 cels
    happy.png  <- Demon_A_Attack01.png   7 cels   (playing = he swings)
    sad.png    <- Demon_A_Hurt.png       4 cels   (over-poked)
    sleep.png  <- last cel of Demon_A_Death.png   1 cel
    bg.jpg     <- Background_09.jpg

Every cel was cropped from 100x100 to a tight 52x52 SQUARE. The pack
draws a small character on a big canvas -- the art filled 21% of its
own frame and he rendered as a thumbnail in a huge room. Square matters:
"width is an exact multiple of height" is how the strip reader counts
frames, so the crop had to stay square rather than hug the artwork.

ONE box was used across every state, not one per state, or he would
change size and footing every time his mood did.

THE REAPER IS NOT IN EITHER OF THESE. Both zips are the FREE tiers and
between them they contain four characters: Soldier, Orc, Demon_A, Blood
Monster_A. A skeleton-summoning reaper is a paid-tier character.
