"""Media routes: screenshot, video stream, stream reset."""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from AutoGLM_GUI.adb_plus import capture_screenshot
from AutoGLM_GUI.schemas import ScreenshotRequest, ScreenshotResponse
from AutoGLM_GUI.scrcpy_stream import ScrcpyStreamer
from AutoGLM_GUI.state import scrcpy_locks, scrcpy_streamers

router = APIRouter()


@router.post("/api/video/reset")
async def reset_video_stream(device_id: str | None = None) -> dict:
    """Reset video stream (cleanup scrcpy server，多设备支持)."""
    if device_id:
        if device_id in scrcpy_locks:
            async with scrcpy_locks[device_id]:
                if device_id in scrcpy_streamers:
                    print(f"[video/reset] Stopping streamer for device {device_id}")
                    scrcpy_streamers[device_id].stop()
                    del scrcpy_streamers[device_id]
                    print(f"[video/reset] Streamer reset for device {device_id}")
                    return {
                        "success": True,
                        "message": f"Video stream reset for device {device_id}",
                    }
                return {
                    "success": True,
                    "message": f"No active video stream for device {device_id}",
                }
        return {"success": True, "message": f"No video stream for device {device_id}"}

    device_ids = list(scrcpy_streamers.keys())
    for dev_id in device_ids:
        if dev_id in scrcpy_locks:
            async with scrcpy_locks[dev_id]:
                if dev_id in scrcpy_streamers:
                    scrcpy_streamers[dev_id].stop()
                    del scrcpy_streamers[dev_id]
    print("[video/reset] All streamers reset")
    return {"success": True, "message": "All video streams reset"}


@router.post("/api/screenshot", response_model=ScreenshotResponse)
def take_screenshot(request: ScreenshotRequest) -> ScreenshotResponse:
    """获取设备截图。此操作无副作用，不影响 PhoneAgent 运行。"""
    try:
        screenshot = capture_screenshot(device_id=request.device_id)
        return ScreenshotResponse(
            success=True,
            image=screenshot.base64_data,
            width=screenshot.width,
            height=screenshot.height,
            is_sensitive=screenshot.is_sensitive,
        )
    except Exception as e:
        return ScreenshotResponse(
            success=False,
            image="",
            width=0,
            height=0,
            is_sensitive=False,
            error=str(e),
        )


@router.websocket("/api/video/stream")
async def video_stream_ws(
    websocket: WebSocket,
    device_id: str | None = None,
):
    """Stream real-time H.264 video from scrcpy server via WebSocket（多设备支持）."""
    await websocket.accept()

    if not device_id:
        await websocket.send_json({"error": "device_id is required"})
        return

    print(f"[video/stream] WebSocket connection for device {device_id}")

    # Debug: Save stream to file for analysis
    # Set to True for debugging (default: False)
    debug_save = False
    debug_file = None
    if debug_save:
        import os
        from pathlib import Path

        debug_dir = Path("debug_streams")
        debug_dir.mkdir(exist_ok=True)
        debug_file_path = debug_dir / f"{device_id}_{int(__import__('time').time())}.h264"
        debug_file = open(debug_file_path, "wb")
        print(f"[video/stream] DEBUG: Saving stream to {debug_file_path}")

    if device_id not in scrcpy_locks:
        scrcpy_locks[device_id] = asyncio.Lock()

    async with scrcpy_locks[device_id]:
        if device_id not in scrcpy_streamers:
            print(f"[video/stream] Creating streamer for device {device_id}")
            scrcpy_streamers[device_id] = ScrcpyStreamer(
                device_id=device_id, max_size=1280, bit_rate=4_000_000
            )

            try:
                print(f"[video/stream] Starting scrcpy server for device {device_id}")
                await scrcpy_streamers[device_id].start()
                print(f"[video/stream] Scrcpy server started for device {device_id}")

                # Read initial chunks and accumulate into a single buffer
                # Then parse the entire buffer to find complete NAL units
                streamer = scrcpy_streamers[device_id]
                accumulated_buffer = bytearray()
                target_size = 50 * 1024  # Accumulate at least 50KB

                print(f"[video/stream] Accumulating initial data (target: {target_size} bytes)...")
                for attempt in range(10):
                    try:
                        # Disable auto-caching - we'll parse the entire buffer at once
                        chunk = await streamer.read_h264_chunk(auto_cache=False)
                        accumulated_buffer.extend(chunk)
                        print(
                            f"[video/stream] Read chunk ({len(chunk)} bytes, total: {len(accumulated_buffer)} bytes)"
                        )
                    except Exception as e:
                        print(f"[video/stream] Failed to read chunk: {e}")
                        await asyncio.sleep(0.5)
                        continue

                    # Check if we have enough data
                    if len(accumulated_buffer) >= target_size:
                        break

                # Now parse the entire accumulated buffer at once
                # This ensures NAL units spanning multiple chunks are detected as complete
                print(f"[video/stream] Parsing accumulated buffer ({len(accumulated_buffer)} bytes)...")
                streamer._cache_nal_units(bytes(accumulated_buffer))

                # Get initialization data
                init_data = streamer.get_initialization_data()
                if not init_data:
                    raise RuntimeError(
                        f"Failed to find complete SPS/PPS/IDR in {len(accumulated_buffer)} bytes"
                    )

                # Send initialization data to first client
                await websocket.send_bytes(init_data)
                print(
                    f"[video/stream] Sent initial data ({len(init_data)} bytes) to first client"
                )

                # Debug: Save to file
                if debug_file:
                    debug_file.write(init_data)
                    debug_file.flush()

            except Exception as e:
                import traceback

                print(f"[video/stream] Failed to start streamer: {e}")
                print(f"[video/stream] Traceback:\n{traceback.format_exc()}")
                scrcpy_streamers[device_id].stop()
                del scrcpy_streamers[device_id]
                try:
                    await websocket.send_json({"error": str(e)})
                except Exception:
                    pass
                return
        else:
            print(f"[video/stream] Reusing streamer for device {device_id}")

            streamer = scrcpy_streamers[device_id]
            # CRITICAL: Send complete initialization data (SPS+PPS+IDR)
            # Without IDR frame, decoder cannot start and will show black screen

            # Wait for initialization data to be ready (max 5 seconds)
            init_data = None
            for attempt in range(10):
                init_data = streamer.get_initialization_data()
                if init_data:
                    break
                print(
                    f"[video/stream] Waiting for initialization data (attempt {attempt + 1}/10)..."
                )
                await asyncio.sleep(0.5)

            if init_data:
                await websocket.send_bytes(init_data)
                print(
                    f"[video/stream] Sent initialization data (SPS+PPS+IDR, {len(init_data)} bytes) for device {device_id}"
                )

                # Debug: Save to file
                if debug_file:
                    debug_file.write(init_data)
                    debug_file.flush()
            else:
                error_msg = f"Initialization data not ready for device {device_id} after 5 seconds"
                print(f"[video/stream] ERROR: {error_msg}")
                try:
                    await websocket.send_json({"error": error_msg})
                except Exception:
                    pass
                return

    streamer = scrcpy_streamers[device_id]

    stream_failed = False
    try:
        chunk_count = 0
        while True:
            try:
                # Disable auto_cache - we only cache once during initialization
                # Later chunks may have incomplete NAL units that would corrupt the cache
                h264_chunk = await streamer.read_h264_chunk(auto_cache=False)
                await websocket.send_bytes(h264_chunk)

                # Debug: Save to file
                if debug_file:
                    debug_file.write(h264_chunk)
                    debug_file.flush()

                chunk_count += 1
                if chunk_count % 100 == 0:
                    print(
                        f"[video/stream] Device {device_id}: Sent {chunk_count} chunks"
                    )
            except ConnectionError as e:
                print(f"[video/stream] Device {device_id}: Connection error: {e}")
                stream_failed = True
                try:
                    await websocket.send_json({"error": f"Stream error: {str(e)}"})
                except Exception:
                    pass
                break

    except WebSocketDisconnect:
        print(f"[video/stream] Device {device_id}: Client disconnected")
    except Exception as e:
        import traceback

        print(f"[video/stream] Device {device_id}: Error: {e}")
        print(f"[video/stream] Traceback:\n{traceback.format_exc()}")
        stream_failed = True
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass

    if stream_failed:
        async with scrcpy_locks[device_id]:
            if device_id in scrcpy_streamers:
                print(f"[video/stream] Resetting streamer for device {device_id}")
                scrcpy_streamers[device_id].stop()
                del scrcpy_streamers[device_id]

    # Debug: Close file
    if debug_file:
        debug_file.close()
        print(f"[video/stream] DEBUG: Closed debug file")

    print(f"[video/stream] Device {device_id}: Stream ended")
