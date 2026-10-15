---
name: dressmaker
description: Play the Steam game Dressmaker through computer use (screenshots, mouse and keyboard) — taking a commission, measuring, sketching, shopping, drafting, laying out and cutting fabric, assembling on the mannequin, sewing seams, accessorizing and completing the commission. Use whenever the user asks Claude to play Dressmaker, continue a dress, or help with any of its stations.
---

# Playing Dressmaker

Lessons from earlier play sessions (Rose's library dress and Prudence's peacock funeral gown), mostly tips the player gave while coaching. The player enjoys watching and coaching: narrate briefly, have fun with the design, and stop immediately when they say "wait" or "stop".

## Input habits that matter

- **Use slow clicks.** Quick clicks often don't register (Continue, scissors, toolbar buttons). Do `mouse_move` → `left_mouse_down` → wait 0.15s → `left_mouse_up`.
- **Aim a little higher than you think.** The pointer has repeatedly landed "a tad too low" on toolbar buttons and the scissors. If a click does nothing, zoom on the target and click its exact center (for the scissors, the pivot screw).
- **Keep the Claude window off the game.** If a click doesn't work, check that the Claude window or another window isn't covering the game.
- **Batch actions** and take fewer screenshots (0.4 scale is enough) once a step is routine. The player wants you to get faster.
- **Right-click** usually drops the held tool (scissors, pencil) or closes a detail view.

## 1. Front desk and commission

- Ring the **bell** to call the next customer and click through the dialogue. Pick dialogue choices that fit the character.
- Read the brief closely. It sets the stat targets (e.g. Elegant 65, Glamour 40, Quality 75) and any rules ("Nothing black!", "cost is no object").
- The **sparkling bell at the top left** always returns you to the front desk.

## 2. Measuring the customer

- Drag the **measuring tape** onto the customer's body, then drag it **up and down** to line it up with the faint guide lines at the **bust, waist and hips**. Each reading registers as you align it.
- When all three are filled in, **Confirm** lights up. Release the tape, then confirm.

## 3. Sketchbook (design)

- Click a piece's **arrows** to flip through options, or click its **name** to see every option with its tag values. The **filter icon** shows only the tags you need.
- The player prefers flipping through the options to see how pieces look together. Balance the stats with what actually looks good. The silhouette doesn't have to hit the targets alone, because **fabric and accessories make up the difference**.
- The **colored pencil** colors sketch panels: pick the pencil, choose a color, then click a panel (each panel colors separately, which allows contrast panels). **The pencil's tip is the point, not the cursor.** It is offset up and to the left (measured at about (−31, −75) once and (−41, −140) another time), so measure it with a screenshot before coloring. Right-click to drop the pencil or change colors.
- **Preview the stats** by dragging fabric/accessory swatches into the swatch boxes next to the sketch. The bars turn green once they pass their target.

## 4. Emporium (shop)

- From the front desk, click the **shelf on the left**. Use the **tag filter** (clear old tags like "Professional" first). Click a bolt to see its details, **right-click to close** it, and use the **left/right arrows** to browse; there are a lot of options.
- Buying a fabric or accessory also **stars** it, so it's easy to find later.
- **Keep in mind how much of each fabric you need.** The player buys extra in **1m batches** to conserve coins. Fabric stays continuous when you add more, so running short isn't a disaster: just buy more.
- Accessories are cheap, small boosts (pearl shank buttons: Elegant +3, 1 coin each). They can wait until the end.

## 5. Pattern drafting: mannequin dials

- Measure the mannequin with the tape (guide lines at bust/waist/hips; the magnifier shows the reading), then **turn that measurement's dial** until it matches the customer's.
- **Within about 0.1 still gives 100% accuracy.** Don't over-polish.
- Moving the right side of the dial up is counter-clockwise (lowers the value). A full turn is about 12 units. A reading only updates while the tape is on that line.
- Confirm → "Cut patterns added to inventory!"

## 6. Cutting table

- **Lay out every piece first, then cut them all at the end.**
- Drag pieces from the pattern list onto the fabric. **Rotate with the ring until the grain arrow turns green**, which usually means level/horizontal. Drag from the **middle** of the ring; grabbing off-center makes the piece swing and lose its angle.
- **Red outline = overlapping or off the fabric**, and the piece can't be cut until it's fixed.
- Pan along the fabric with the **left/right arrow keys** (tap repeatedly; holding only moves one step).
- **Pieces are deceptively small** compared with the skirt panels. There's usually more room than it looks, often along the top edge. Nest the big panels diagonally and tuck the small pieces into gaps.
- **Bias pieces** (bows, ribbons, strips with a diagonal grain arrow) go **diagonally**. A bias piece also fits fabric that's narrower than its length.
- Contrast pieces (a bow, a sash, a center panel) can come from a **different fabric**. Lay out and cut everything for the current fabric, put it away, then switch.
- **Cutting:** pick up the **scissors** (slow press, aim at the pivot), then **click every piece quickly**; no need to wait between clicks. **Right-click** to put the scissors away, then click the **put-away button at the top right** (paper with a right arrow) to send every cut piece to the inventory.
- **Switching fabric:** **cut and put away first**, then use the Fabric tab and click the new fabric.
- Tiles in the pattern list reflow after each placement. Hover over a tile to confirm which piece it is before dragging, or take tiles from the end of the list.

## 7. Mannequin assembly

- **Hover over a piece to see where it goes.** Pieces snap into place when dropped on the torso.
- **Back pieces only place when the mannequin faces back.** Turn it by dragging horizontally across the lower part of the screen (or with the arrow keys).
- Afterwards, turn the mannequin all the way around and look for **floating pieces**. Drag each one onto the body (or press it onto its spot) until everything hangs as one garment.

## 8. Sewing

- Click a **seam marker** (flower icon) to open that seam, then **hold Space** to sew. **Sewing assist steers for you**, so don't use the arrow keys or A/D to steer.
- **Corners and curves:** **stop just before the corner, then tap Space** (short presses of about 0.3–0.6s with short pauses) **until the needle turns to the new direction, then floor it.**
- **Speed:** **S** slows the machine (corners, curvy bodice/sleeve/armhole seams), and **W** speeds it up (long straight seams). You don't need to slow down at the end of a seam; let it speed through.
- Watch the accuracy %. Taking corners too fast has dropped it to about 60%.
- One seam can clear several markers. **Turn the mannequin** to find the back and side markers, and keep going until none are left.
- Quality rises with each seam. It's fine to finish every seam even after the target is met.

## 9. Finishing

- **Finish Dress → accessories:** drag buttons/appliqués/feathers onto the dress (e.g. pearl buttons down the bodice and on the cuffs). Accessories can be angled and resized (feathers, for example).
- **Photo:** choose a backdrop in the environment controls (the library backdrop looked great), then **Take Photo**. No need to save it.
- **Complete Commission**, then click through the customer's reaction.
- Afterwards, click the **customer's icon** (friendship unlocks new patterns, which get added to the sketchbook) and **click your rank** to rank up. Higher rank unlocks new Emporium stock.

## Design inspiration the player liked

Contrasting center panels or godets, lace at the hems, and a small contrasting bow or collar. Take the brief literally and with flair: Prudence got a peacock-teal velvet gown with a gold center panel, sash and bow for a funeral.
