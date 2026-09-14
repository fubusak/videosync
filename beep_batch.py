"""Compare detected beep events across a batch of recordings."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class BeepCandidate:
    onset: float
    frequency: float
    duration: float
    confidence: float


def merge_candidates(candidates, max_gap=.015):
    """Deduplicate overlapping bands/channels with 15 ms analysis tolerance.

    Longer gaps are handled as reference-supported alternatives, preserving
    the individual events when they may be separate clear beeps.
    """
    groups = []
    for candidate in sorted(candidates, key=lambda item: item.onset):
        end = candidate.onset + candidate.duration
        for group in reversed(groups):
            if (candidate.onset <= group['end'] + max_gap and
                    max(group['high'], candidate.frequency) - min(group['low'], candidate.frequency) <= 25):
                group['end'] = max(group['end'], end)
                group['low'] = min(group['low'], candidate.frequency)
                group['high'] = max(group['high'], candidate.frequency)
                if candidate.confidence > group['best'].confidence:
                    group['best'] = candidate
                break
        else:
            groups.append(dict(onset=candidate.onset, end=end, low=candidate.frequency,
                               high=candidate.frequency, best=candidate))
    return [BeepCandidate(group['onset'], group['best'].frequency,
                          group['end'] - group['onset'], group['best'].confidence)
            for group in groups]


def select_batch(candidate_lists):
    """Select the earliest group consistent in frequency AND observed duration.

    All frequencies must fit a 40 Hz span. Observed durations may differ by
    up to 30% of the longest event, or 40 ms for short beeps. A clear reference
    permits up to 40% missing duration in a noisy recording. These allowances
    concern noisy measurements, not changes to the actual playback speed.
    """
    if not 2 <= len(candidate_lists) <= 4:
        raise ValueError('Batch matching requires 2–4 recordings.')
    if any(not candidates for candidates in candidate_lists):
        raise ValueError('No matching beep in every recording: at least one file has no candidates.')
    for candidates in candidate_lists:
        for item in candidates:
            if not all(math.isfinite(value) for value in (item.onset, item.frequency, item.duration, item.confidence)):
                raise ValueError('Beep candidate values must be finite.')
            if item.onset < 0 or item.duration <= 0 or item.frequency <= 0:
                raise ValueError('Invalid beep candidate timing or frequency.')
    candidate_lists = add_masked_variants(candidate_lists)
    ordered = [sorted(candidates, key=lambda item: (item.onset, item.frequency, item.duration, -item.confidence))
               for candidates in candidate_lists]
    best_key, best_group = None, None

    def compatible(group, final=False):
        frequencies = [item.frequency for item in group]
        durations = [item.duration for item in group]
        if max(frequencies) - min(frequencies) > 40:
            return False
        longest = max(durations)
        if longest - min(durations) <= max(.04, .30 * longest) + 1e-9:
            return True
        # Prefix checks are permissive: a clear reference can be in a later
        # recording. Final validation requires that reference in this group.
        clear_reference = any(item.duration == longest and item.confidence >= .9 for item in group)
        if final and not clear_reference:
            return False
        return all(longest - item.duration <= max(.04, (.40 if item.confidence < .9 else .30) * longest) + 1e-9
                   for item in group)

    def search(group, total):
        nonlocal best_key, best_group
        index = len(group)
        if index == len(ordered):
            if not compatible(group, final=True):
                return
            frequencies = [item.frequency for item in group]
            durations = [item.duration for item in group]
            mismatch = (max(frequencies) - min(frequencies)) / 40 + (max(durations) - min(durations)) / max(durations)
            key = (total, mismatch, -sum(item.confidence for item in group))
            if best_key is None or key < best_key:
                best_key, best_group = key, list(group)
            return
        for item in ordered[index]:
            lower_bound = total + item.onset + sum(items[0].onset for items in ordered[index + 1:])
            if best_key is not None and lower_bound > best_key[0]:
                break
            proposed = group + [item]
            if not compatible(proposed):
                continue
            if any(not any(compatible(proposed + [other]) for other in future)
                   for future in ordered[index + 1:]):
                continue
            search(proposed, total + item.onset)

    search([], 0)
    if best_group is None:
        raise ValueError('No common beep: candidate frequencies or durations disagree across the batch. '
                         'Check the files, frequency and search window.')
    return best_group


def add_masked_variants(candidate_lists):
    """Use clear beeps in other recordings to test fragmented noisy events.

    Do not globally join separate beeps. Only propose a joined alternative
    when a clear other recording supports both its frequency and full span.
    Preserve the observed onset rather than inventing a hidden start time.
    """
    result = []
    for index, candidates in enumerate(candidate_lists):
        expanded = set(candidates)
        references = [item for other_index, items in enumerate(candidate_lists) if other_index != index
                      for item in items if item.confidence >= .9]
        for reference in references:
            matching = sorted((item for item in candidates if item.confidence < .9 and
                               abs(item.frequency - reference.frequency) <= 40), key=lambda item: item.onset)
            for start_index, first in enumerate(matching):
                parts = [first]
                end = first.onset + first.duration
                for other in matching[start_index + 1:]:
                    if other.onset - end > min(.3, reference.duration):
                        break
                    frequencies = [item.frequency for item in parts] + [reference.frequency, other.frequency]
                    if max(frequencies) - min(frequencies) > 40:
                        continue
                    new_end = max(end, other.onset + other.duration)
                    span = new_end - first.onset
                    if span > reference.duration + max(.04, .30 * reference.duration):
                        continue
                    parts.append(other)
                    end = new_end
                    allowance = .40 if span < reference.duration else .30
                    if abs(span - reference.duration) <= max(.04, allowance * max(span, reference.duration)):
                        strongest = max(parts, key=lambda item: item.confidence)
                        expanded.add(BeepCandidate(first.onset, strongest.frequency, span, strongest.confidence))
        result.append(list(expanded))
    return result
