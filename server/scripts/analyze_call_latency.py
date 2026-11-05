"""分析 CALL_LATENCY 日志；ACK 是客户端确认往返，不是扬声器播放时间。"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def read_events(paths):
    decoder = json.JSONDecoder()
    seen = set()
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            if "CALL_LATENCY " not in line:
                continue
            event, _ = decoder.raw_decode(line.split("CALL_LATENCY ", 1)[1])
            identity = json.dumps(event, sort_keys=True)
            if identity not in seen:
                seen.add(identity)
                yield event


def index_events(events):
    groups = defaultdict(list)
    decisions = []
    retrieval_events = []
    turns = {}
    stops = {}
    for event in events:
        key = (event.get("process_run"), event["call_id"])
        if event["event"] == "input.provider_speech_stopped":
            stops[(*key, event["turn_seq"])] = event
        if event["event"] == "turn.final":
            turns[(*key, event["turn_seq"])] = event
        if event["event"].startswith("retrieval."):
            retrieval_events.append(event)
        if event["event"] == "retrieval.decision":
            decisions.append(event)
        if event.get("response_id"):
            groups[(*key, event["response_id"])].append(event)
    return groups, decisions, retrieval_events, turns, stops


def analyze(events):
    events = list(events)
    groups, decisions, retrieval_events, turns, stops = index_events(events)
    speech_starts = {
        (e.get("process_run"), e["call_id"], e.get("item_id")): e
        for e in events
        if e["event"] == "input.speech_started"
    }
    responses = []
    for key, rows in groups.items():
        rows.sort(key=lambda row: row["monotonic_ns"])
        first = {}
        for row in rows:
            first.setdefault(row["event"], row)
        if not any(name.startswith("audio.") for name in first):
            continue
        response = {"process_run": key[0], "call_id": key[1], "response_id": key[2]}
        pairs = {
            "first_packet_hold_ms": ("audio.generated", "audio.hold_released"),
            "first_packet_to_enqueue_ms": ("audio.generated", "audio.enqueued"),
            "first_packet_to_sent_ms": ("audio.generated", "audio.sent"),
            "first_packet_to_ack_ms": ("audio.generated", "audio.ack"),
            "first_packet_to_stream_completed_ms": ("audio.generated", "audio.playback_completed"),
        }
        for name, (start, end) in pairs.items():
            response[name] = delta(first.get(start), first.get(end))
        for name, (start, end) in {
            "dispatch_wait_ms": ("reply.response", "tts.requested"),
            "tts_queue_ms": ("tts.requested", "tts.started"),
            "tts_first_packet_synthesis_ms": ("tts.started", "tts.synthesized"),
            "tts_delivery_ms": ("tts.synthesized", "audio.generated"),
            "tts_full_synthesis_ms": ("tts.started", "tts.finished"),
        }.items():
            response[name] = delta(first.get(start), first.get(end))
        response.update(packet_details(rows))
        mapping = first.get("reply.response", {})
        final = turns.get((*key[:2], mapping.get("turn_seq")), {})
        stop = stops.get((*key[:2], mapping.get("turn_seq")), {})
        origin, response["speech_end_basis"] = speech_endpoint(final, stop)
        estimated = stop.get("estimated_end_ns")
        estimate = {"monotonic_ns": estimated} if estimated is not None else None
        response["estimated_end_to_provider_stop_ms"] = delta(estimate, stop or None)
        response["estimated_end_to_first_ack_ms"] = delta(estimate, first.get("audio.ack"))
        interrupt = first.get("reply.interrupt", {})
        speech = speech_starts.get((*key[:2], interrupt.get("item_id"))) if interrupt.get("item_id") else None
        requests = {e["stop_seq"]: e for e in rows if e["event"] == "audio.stop_requested"}
        confirms = {e["stop_seq"]: e for e in rows if e["event"] == "audio.stop_confirmed" and e.get("accepted")}
        response["stop_confirmations"] = [
            {
                "stop_seq": seq,
                "stream_id": req["stream_id"],
                "confirmation_ms": delta(req, confirms.get(seq)),
                "speech_started_to_stop_request_ms": delta(speech, req),
                "speech_started_to_confirmation_ms": delta(speech, confirms.get(seq)),
            }
            for seq, req in requests.items()
        ]
        response["turn_seq"] = mapping.get("turn_seq")
        response["invalidated"] = "reply.invalidated" in first
        response["first_sent_ns"] = first.get("audio.sent", {}).get("monotonic_ns")
        response["first_generated_ns"] = first.get("audio.generated", {}).get("monotonic_ns")
        response["first_ack_ns"] = first.get("audio.ack", {}).get("monotonic_ns")
        response["model_response_id"] = mapping.get("model_response_id")
        response["segment_index"] = mapping.get("segment_index")
        response["speech_end_to_first_packet_ms"] = delta(origin, first.get("audio.generated"))
        response["speech_end_to_first_sent_ms"] = delta(origin, first.get("audio.sent"))
        response["speech_end_to_first_ack_ms"] = delta(origin, first.get("audio.ack"))
        response["provisional"] = first.get("audio.generated", {}).get("provisional")
        responses.append(response)
    business_turns = summarize_turns(responses, turns, stops)
    return {
        "turn_summary": (
            turn_statistics(business_turns)
            if len({t["speech_end_basis"] for t in business_turns}) <= 1
            else {"turn_count": len(business_turns), "mixed_bases": True}
        ),
        "turn_summary_by_basis": {
            basis: turn_statistics([t for t in business_turns if t["speech_end_basis"] == basis])
            for basis in sorted({t["speech_end_basis"] for t in business_turns})
        },
        "measurement": (
            "首个音频 ACK 作为用户听到首包的代理，包含客户端处理与上行确认，不代表播放头实测。"
            "completed 是整段播放结束。缺失值为 null。"
        ),
        "responses": responses,
        "turns": business_turns,
        "retrievals": summarize_retrievals(retrieval_events),
        "model_responses": summarize_models(groups),
        "retrieval_decisions": decisions,
        "retrieval_events": retrieval_events,
    }


def turn_statistics(turns):
    import math
    import statistics

    result = {"turn_count": len(turns)}
    for metric in (
        "speech_end_to_first_packet_ms",
        "speech_end_to_first_sent_ms",
        "speech_end_to_first_ack_ms",
        "estimated_end_to_provider_stop_ms",
        "estimated_end_to_first_ack_ms",
    ):
        values = sorted(row[metric] for row in turns if row[metric] is not None)
        result[metric] = {
            "count": len(values),
            "p50_ms": statistics.median(values) if values else None,
            "p95_ms": values[math.ceil(len(values) * 0.95) - 1] if values else None,
        }
    return result


def summarize_turns(responses, finals, stops):
    turns = []
    for key in sorted(finals.keys() | stops.keys(), key=str):
        candidates = [
            r for r in responses if (r["process_run"], r["call_id"], r["turn_seq"]) == key and not r["provisional"]
        ]
        ack_candidates = candidates
        candidates = [r for r in candidates if not r["invalidated"]]
        first = min(
            (r for r in candidates if r["first_sent_ns"] is not None), key=lambda r: r["first_sent_ns"], default=None
        )
        ack = min(
            (r for r in ack_candidates if r["first_ack_ns"] is not None), key=lambda r: r["first_ack_ns"], default=None
        )
        generated = min(
            (r for r in candidates if r["first_generated_ns"] is not None),
            key=lambda r: r["first_generated_ns"],
            default=None,
        )
        stop = stops.get(key, {})
        end = stop.get("estimated_end_ns")
        row = dict(
            estimated_end_to_provider_stop_ms=(stop["monotonic_ns"] - end) / 1e6 if end is not None else None,
            estimated_end_to_first_ack_ms=ack["estimated_end_to_first_ack_ms"] if ack else None,
            process_run=key[0],
            call_id=key[1],
            turn_seq=key[2],
            speech_end_basis=speech_endpoint(finals.get(key, {}), stops.get(key, {}))[1],
            first_ack_response_id=ack["response_id"] if ack else None,
            first_response_id=first["response_id"] if first else None,
        )
        row["speech_end_to_first_sent_ms"] = first["speech_end_to_first_sent_ms"] if first else None
        row["speech_end_to_first_packet_ms"] = generated["speech_end_to_first_packet_ms"] if generated else None
        row["speech_end_to_first_ack_ms"] = ack["speech_end_to_first_ack_ms"] if ack else None
        turns.append(row)
    return turns


def summarize_retrievals(events):
    groups = defaultdict(list)
    for event in events:
        if event.get("tool_call_id"):
            groups[(event.get("process_run"), event["call_id"], event["tool_call_id"])].append(event)
    result = []
    for key, rows in groups.items():
        points = {r["event"]: r for r in sorted(rows, key=lambda r: r["monotonic_ns"])}
        identity = next((r for r in rows if r.get("turn_seq") is not None), rows[0])
        result.append(
            dict(
                process_run=key[0],
                call_id=key[1],
                tool_call_id=key[2],
                turn_seq=identity.get("turn_seq"),
                model_response_id=identity.get("response_id"),
                tool_ms=delta(points.get("retrieval.tool_requested"), points.get("retrieval.tool_completed")),
                submit_ms=delta(points.get("retrieval.tool_completed"), points.get("retrieval.tool_submitted")),
                status=points.get("retrieval.phases", {}).get("status"),
                phases=points.get("retrieval.phases", {}).get("phases", {}),
            )
        )
    return result


def summarize_models(groups):
    result = []
    for key, rows in groups.items():
        points = {}
        for row in sorted(rows, key=lambda r: r["monotonic_ns"]):
            points.setdefault(row["event"], row)
        if "reply.generation_started" not in points:
            continue
        link = points.get("reply.model_link", {})
        parent = link.get("parent_response_id")
        continuation = max(
            (
                event
                for event in groups.get((*key[:2], parent), ())
                if event["event"] == "reply.continuation_requested" and event["monotonic_ns"] <= link["monotonic_ns"]
            ),
            key=lambda event: event["monotonic_ns"],
            default=None,
        )
        result.append(
            dict(
                process_run=key[0],
                call_id=key[1],
                response_id=key[2],
                parent_response_id=parent,
                continuation_to_first_text_delta_ms=delta(continuation, points.get("reply.first_text_delta")),
                first_text_delta_ms=delta(points.get("reply.model_link"), points.get("reply.first_text_delta")),
                first_delta_to_segment_ms=delta(
                    points.get("reply.first_text_delta"), points.get("reply.segment_ready")
                ),
                first_segment_ms=delta(points.get("reply.generation_started"), points.get("reply.segment_ready")),
                generation_ms=delta(points.get("reply.generation_started"), points.get("reply.generation_finished")),
            )
        )
    return result


def speech_endpoint(final, stop):
    speech_end = stop.get("monotonic_ns", final.get("speech_end_ns"))
    if speech_end is None:
        return None, "unavailable"
    basis = "provider_speech_stopped_received" if stop else final.get("speech_end_basis", "audio_ingress_estimate")
    return {"monotonic_ns": speech_end}, basis


def packet_details(rows):
    response = {}
    packets = defaultdict(dict)
    for row in rows:
        if "packet_index" in row:
            packets[row["packet_index"]].setdefault(row["event"], row)
    response["generated_packets"] = [
        {
            "packet_index": index,
            "hold_ms": delta(points.get("audio.generated"), points.get("audio.hold_released")),
            "emit_wait_ms": delta(points.get("audio.hold_released"), points.get("audio.emit_completed")),
        }
        for index, points in sorted(packets.items())
    ]
    seqs = defaultdict(dict)
    attempts = defaultdict(int)
    for row in rows:
        if "seq" in row and row["seq"] is not None:
            seqs[row["seq"]].setdefault(row["event"], row)
            if row["event"] == "audio.sent":
                attempts[row["seq"]] += 1
    response["wire_packets"] = [
        {
            "seq": seq,
            "enqueue_to_sent_ms": delta(points.get("audio.enqueued"), points.get("audio.sent")),
            "sent_to_ack_ms": delta(points.get("audio.sent"), points.get("audio.ack")),
            "send_attempts": attempts[seq],
        }
        for seq, points in sorted(seqs.items())
    ]
    return response


def delta(start, end):
    if start is None or end is None:
        return None
    return round((end["monotonic_ns"] - start["monotonic_ns"]) / 1_000_000, 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(analyze(read_events(args.logs)), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
