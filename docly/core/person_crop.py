"""Choose a crop for a photo without asking: frame the person, not the middle.

A plain centred crop of a tall phone photo often cuts off the top of the
head. Batch mode has no one to drag the frame, so Docly uses the same
person matte as the background tool (:mod:`docly.core.background`):

* take the largest box with the preset's shape that fits the photo
  (keeping as much as possible, like a careful centred crop),
* move it sideways so the head is in the middle,
* move it up or down so there is a little space above the head.

If no person is found, it falls back to the centred crop and says so.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from docly.core.background import Segmenter, default_segmenter, matte_for
from docly.core.compress import CancelCheck
from docly.core.image_io import LoadedImage
from docly.core.resize import CropBox, centered_crop
from docly.presets.models import Preset

HEADROOM = 0.10  # space above the head, as a share of the crop's height
HEAD_BAND = 0.15  # the top 15 % of the person is treated as the head
MIN_PERSON_SHARE = 0.03  # less than this much of the photo is "no person found"


@dataclass(frozen=True)
class PersonCrop:
    box: CropBox | None  # None: keep the whole photo (preset has no fixed shape)
    found: bool  # a person was found
    note: str = ""


def person_crop(
    loaded: LoadedImage,
    preset: Preset,
    segmenter: Segmenter | None = None,
    cancel: CancelCheck | None = None,
) -> PersonCrop:
    """A crop box in image pixels that frames the person for ``preset``."""
    width, height = loaded.size
    ratio = preset.ratio
    if ratio is None:
        return PersonCrop(None, True)
    fallback = centered_crop(width, height, ratio)
    matte = matte_for(loaded.image, segmenter or default_segmenter(), cancel)
    person = matte > 0.5
    if person.mean() < MIN_PERSON_SHARE:
        return PersonCrop(fallback, False, "No person found, so the photo was cropped in the middle. Check the crop.")

    mh, mw = matte.shape
    rows = np.flatnonzero(person.any(axis=1))
    top, bottom = rows[0], rows[-1]
    band_end = top + max(1, int((bottom - top + 1) * HEAD_BAND))
    head_x = float(np.nonzero(person[top:band_end])[1].mean())

    # Matte → image pixels.
    sx, sy = width / mw, height / mh
    head_top = top * sy
    head_cx = (head_x + 0.5) * sx

    box_w, box_h = fallback.w, fallback.h
    x = round(head_cx - box_w / 2)
    y = round(head_top - HEADROOM * box_h)
    x = min(max(x, 0), width - box_w)
    y = min(max(y, 0), height - box_h)
    note = ""
    if head_top < HEADROOM * box_h * 0.5:
        note = "The head is very close to the top of the photo. Check the crop."
    return PersonCrop(CropBox(int(x), int(y), int(box_w), int(box_h)), True, note)
