package com.hypper.tv;

import android.media.Image;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;

import java.io.File;
import java.nio.ByteBuffer;

/**
 * Sequential MediaCodec decoder: reads a local mp4, decodes frames and pushes
 * downscaled RGB24 frames into the native core at approximately the requested
 * rate. MediaMetadataRetriever with OPTION_CLOSEST had to decode from the
 * previous keyframe for every frame (~0.5 s each on the test device), which is
 * why the wall used to visibly advance only every couple of seconds.
 */
final class VideoPump {

    interface Sink {
        void push(byte[] rgb, int w, int h);

        boolean running();

        void line(String s);
    }

    private VideoPump() {
    }

    static boolean pump(File file, int wallW, int wallH, float fps, long startMs, Sink sink) {
        MediaExtractor ex = new MediaExtractor();
        MediaCodec codec = null;
        String mime = null;
        MediaFormat fmt = null;
        byte[] rgb = new byte[wallW * wallH * 3];
        int sent = 0;
        try {
            ex.setDataSource(file.getAbsolutePath());
            int track = -1;
            for (int i = 0; i < ex.getTrackCount(); i++) {
                MediaFormat f = ex.getTrackFormat(i);
                String m = f.getString(MediaFormat.KEY_MIME);
                if (m != null && m.startsWith("video/")) {
                    track = i;
                    fmt = f;
                    mime = m;
                    break;
                }
            }
            if (track < 0 || fmt == null || mime == null) {
                sink.line("видео: дорожка не найдена");
                return false;
            }
            int width = fmt.getInteger(MediaFormat.KEY_WIDTH);
            int height = fmt.getInteger(MediaFormat.KEY_HEIGHT);
            sink.line("видео: MediaCodec " + mime + " " + width + "x" + height);

            codec = MediaCodec.createDecoderByType(mime);
            codec.configure(fmt, null, null, 0);
            codec.start();
            ex.selectTrack(track);
            if (startMs > 0) {
                ex.seekTo(startMs * 1000L, MediaExtractor.SEEK_TO_PREVIOUS_SYNC);
            }

            final long stepMs = Math.max(1L, Math.round(1000.0 / Math.max(0.2f, fps)));
            long nextPush = System.currentTimeMillis();
            long baseWall = -1L;
            long basePts = 0L;
            boolean inputDone = false;
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            long startedAt = System.currentTimeMillis();

            while (sink.running()) {
                if (!inputDone) {
                    int inIdx = codec.dequeueInputBuffer(5000);
                    if (inIdx >= 0) {
                        ByteBuffer buf = codec.getInputBuffer(inIdx);
                        int size = buf == null ? -1 : ex.readSampleData(buf, 0);
                        if (size < 0) {
                            codec.queueInputBuffer(inIdx, 0, 0, 0,
                                    MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                            inputDone = true;
                        } else {
                            codec.queueInputBuffer(inIdx, 0, size, ex.getSampleTime(), 0);
                            ex.advance();
                        }
                    }
                }
                int outIdx = codec.dequeueOutputBuffer(info, 5000);
                if (outIdx >= 0) {
                    if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) {
                        codec.releaseOutputBuffer(outIdx, false);
                        ex.seekTo(0, MediaExtractor.SEEK_TO_CLOSEST_SYNC);
                        codec.flush();
                        inputDone = false;
                        baseWall = -1L;
                        continue;
                    }
                    long now = System.currentTimeMillis();
                    long ptsMs = info.presentationTimeUs / 1000;
                    if (baseWall < 0) {
                        baseWall = now;
                        basePts = ptsMs;
                    }
                    // Keep video time in step with wall clock (1x playback).
                    long target = basePts + (now - baseWall);
                    if (ptsMs > target) {
                        long d = Math.min(ptsMs - target, 50L);
                        try {
                            Thread.sleep(d);
                        } catch (InterruptedException ignored) {
                        }
                        now = System.currentTimeMillis();
                    }
                    if (info.size > 0 && now >= nextPush) {
                        Image img = codec.getOutputImage(outIdx);
                        if (img != null) {
                            yuvToRgb(img, wallW, wallH, rgb);
                            img.close();
                            sink.push(rgb, wallW, wallH);
                            sent++;
                            nextPush = now + stepMs;
                            if (sent % 10 == 0) {
                                long sec = Math.max(1, (now - startedAt) / 1000);
                                sink.line("кадров: " + sent + " (" + (sent / sec) + "/с), "
                                        + (info.presentationTimeUs / 1000000) + " с");
                            }
                        }
                    }
                    codec.releaseOutputBuffer(outIdx, false);
                }
            }
            return sent > 0;
        } catch (Throwable e) {
            sink.line("видео: MediaCodec — " + e);
            return false;
        } finally {
            try {
                if (codec != null) {
                    codec.stop();
                    codec.release();
                }
            } catch (Throwable ignored) {
            }
            try {
                ex.release();
            } catch (Throwable ignored) {
            }
        }
    }

    /** YUV_420_888 (any plane layout) -> downscaled RGB24, BT.601. */
    private static void yuvToRgb(Image img, int wallW, int wallH, byte[] out) {
        Image.Plane[] planes = img.getPlanes();
        ByteBuffer yb = planes[0].getBuffer();
        ByteBuffer ub = planes[1].getBuffer();
        ByteBuffer vb = planes[2].getBuffer();
        int sy = planes[0].getRowStride();
        int sp = planes[0].getPixelStride();
        int us = planes[1].getRowStride();
        int up = planes[1].getPixelStride();
        int vs = planes[2].getRowStride();
        int vp = planes[2].getPixelStride();
        int iw = img.getWidth();
        int ih = img.getHeight();
        int o = 0;
        for (int oy = 0; oy < wallH; oy++) {
            int srcY = oy * ih / wallH;
            int yRow = srcY * sy;
            int uvRowU = (srcY / 2) * us;
            int uvRowV = (srcY / 2) * vs;
            for (int ox = 0; ox < wallW; ox++) {
                int srcX = ox * iw / wallW;
                int y = (yb.get(yRow + srcX * sp) & 0xFF) - 16;
                int u = (ub.get(uvRowU + (srcX / 2) * up) & 0xFF) - 128;
                int v = (vb.get(uvRowV + (srcX / 2) * vp) & 0xFF) - 128;
                int c = 298 * y;
                int r = (c + 409 * v + 128) >> 8;
                int g = (c - 100 * u - 208 * v + 128) >> 8;
                int b = (c + 516 * u + 128) >> 8;
                out[o++] = (byte) (r < 0 ? 0 : (r > 255 ? 255 : r));
                out[o++] = (byte) (g < 0 ? 0 : (g > 255 ? 255 : g));
                out[o++] = (byte) (b < 0 ? 0 : (b > 255 ? 255 : b));
            }
        }
    }
}