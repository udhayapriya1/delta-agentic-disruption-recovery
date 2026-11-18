"""Render actual browser footage into seven narrated 1080p chapters.

Cloud wait time is shortened, explicitly labeled on-screen. Result inspection
and actual execution are preserved; no response is generated for the video.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'video/demo';RUN=ROOT/'tmp/recording';RAW=RUN/'footage';OUT.mkdir(parents=True,exist_ok=True)
FF=imageio_ffmpeg.get_ffmpeg_exe()
chapters=json.loads((OUT/'narration.json').read_text())
manifest=json.loads((RAW/'manifest.json').read_text())
if len(manifest)!=7 or not all(x['execution_success'] for x in manifest):raise SystemExit('All seven actual execution chapters must succeed')
font='/System/Library/Fonts/Supplemental/Arial.ttf'
subtitle=[]
def timestamp(t):
    ms=round(t*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
for i,ch in enumerate(chapters):
    work=RUN/f'edit-{i}';work.mkdir(exist_ok=True)
    text=work/'narration.txt';text.write_text(ch['text'])
    audio=work/'voice.aiff'
    subprocess.run(['say','-v','Samantha','-r','166','-f',str(text),'-o',str(audio)],check=True)
    probe=subprocess.run([FF,'-i',str(audio)],capture_output=True,text=True).stderr
    match=re.search(r'Duration: (\d+):(\d+):([\d.]+)',probe)
    audio_duration=int(match[1])*3600+int(match[2])*60+float(match[3])
    if audio_duration>ch['duration']-1:raise RuntimeError(f'Narration too long: {ch["chapter"]}: {audio_duration}')
    files=sorted((RAW/f'{i:02}').glob('*.jpg'));target=ch['duration']*2
    # Keep click and response inspection at original speed. Compress only the
    # cloud waiting interval; hold the final screen when a chapter is short.
    if len(files)<=target:indices=list(range(len(files)))+[len(files)-1]*(target-len(files))
    else:
        first=8;tail=min(42,target-first-8);middle=target-first-tail
        lo=first;hi=len(files)-tail
        indices=list(range(first))+[lo+int((hi-lo)*j/middle) for j in range(middle)]+list(range(len(files)-tail,len(files)))
    words=ch['text'].split();chunks=[]
    while words:
        n=min(17,len(words));chunks.append(' '.join(words[:n]));words=words[n:]
    speech_start=1.2;chunk_duration=audio_duration/len(chunks)
    for j,chunk in enumerate(chunks):
        subtitle.append((ch['start']+speech_start+j*chunk_duration,ch['start']+speech_start+(j+1)*chunk_duration,chunk))
    for frame,k in enumerate(indices):
        im=Image.open(files[k]).convert('RGB');im=im.resize((1920,972),Image.Resampling.LANCZOS)
        canvas=Image.new('RGB',(1920,1080),'#050e19');canvas.paste(im,(0,0));draw=ImageDraw.Draw(canvas)
        # Persistent disclosure makes edit and console provenance explicit.
        draw.rounded_rectangle((1160,9,1897,40),radius=6,fill='#172b40')
        draw.text((1175,15),'ACTUAL EXECUTION • PRESENTER CONSOLE • CLOUD WAITS SHORTENED',font=ImageFont.truetype(font,15),fill='#b9d5ec')
        draw.text((35,983),ch['title'].upper(),font=ImageFont.truetype(font,16),fill='#67ddd3')
        local_time=frame/2
        chunk_index=int((local_time-speech_start)/chunk_duration)
        if local_time>=speech_start and 0<=chunk_index<len(chunks):
            import textwrap
            lines=textwrap.wrap(chunks[chunk_index],width=114)
            for line_index,line in enumerate(lines[:2]):
                box=draw.textbbox((0,0),line,font=ImageFont.truetype(font,26));width=box[2]-box[0]
                draw.text(((1920-width)/2,1004+line_index*33),line,font=ImageFont.truetype(font,26),fill='#f1f5fb')
        canvas.save(work/f'{frame:04}.jpg',quality=92)
    subprocess.run([FF,'-y','-framerate','2','-i',str(work/'%04d.jpg'),'-i',str(audio),'-filter_complex',f'[0:v]fps=24,format=yuv420p[v];[1:a]adelay=1200|1200,apad,atrim=0:{ch["duration"]},loudnorm=I=-16:TP=-1.5:LRA=11[a]','-map','[v]','-map','[a]','-t',str(ch['duration']),'-c:v','libx264','-preset','fast','-crf','19','-c:a','aac','-b:a','192k',str(work/'chapter.mp4')],check=True,stdout=subprocess.DEVNULL,stderr=(work/'encode.log').open('w'))
    print('Rendered '+ch['chapter'],flush=True)
(OUT/'captions.srt').write_text('\n\n'.join(f'{i+1}\n{timestamp(a)} --> {timestamp(b)}\n{text}' for i,(a,b,text) in enumerate(subtitle))+'\n')
listing=RUN/'chapters.txt';listing.write_text(''.join(f"file '{RUN/f'edit-{i}'/'chapter.mp4'}'\n" for i in range(7)))
metadata=RUN/'chapters.ffmeta';metadata.write_text(';FFMETADATA1\ntitle=Delta Agentic Disruption Recovery — Actual Execution\n'+''.join(f'[CHAPTER]\nTIMEBASE=1/1000\nSTART={c["start"]*1000}\nEND={(c["start"]+c["duration"])*1000}\ntitle={c["title"]}\n' for c in chapters))
target=OUT/'delta-recovery-live-demo.mp4'
subprocess.run([FF,'-y','-f','concat','-safe','0','-i',str(listing),'-i',str(OUT/'captions.srt'),'-i',str(metadata),'-map','0:v','-map','0:a','-map','1:0','-map_metadata','2','-map_chapters','2','-c','copy','-c:s','mov_text','-movflags','+faststart',str(target)],check=True,stdout=subprocess.DEVNULL,stderr=(RUN/'final-encode.log').open('w'))
shutil.copy(RAW/'book.png',OUT/'poster.png')
shutil.copy(RUN/'execution.json',OUT/'execution.json')
shutil.copy(RUN/'audit.jsonl',OUT/'api-trace.jsonl')
shutil.copy(RUN/'execution-verification.json',OUT/'execution-verification.json')
probe=subprocess.run([FF,'-i',str(target)],capture_output=True,text=True).stderr
if 'Referenced QT chapter track not found' in probe:
    # The bundled FFmpeg 9 muxer can emit dangling QuickTime chapter-track
    # references when explicit captions are mapped. Keep Nero chpl chapters,
    # neutralize only the dangling tref boxes, preserving sizes and offsets.
    import struct
    data=bytearray(target.read_bytes())
    def repair(start,end,parent=None):
        pos=start
        while pos+8<=end:
            size=struct.unpack_from('>I',data,pos)[0];kind=bytes(data[pos+4:pos+8]);header=8
            if size==1:size=struct.unpack_from('>Q',data,pos+8)[0];header=16
            if size==0:size=end-pos
            if size<header or pos+size>end:raise ValueError('Invalid MP4 container box')
            if kind==b'tref' and parent==b'trak' and bytes(data[pos+header+4:pos+header+8])==b'chap':
                data[pos+4:pos+8]=b'free'
            elif kind in (b'moov',b'trak'):repair(pos+header,pos+size,kind)
            pos+=size
    repair(0,len(data));target.write_bytes(data)
    probe=subprocess.run([FF,'-i',str(target)],capture_output=True,text=True).stderr
verify={'actual_execution':True,'all_seven_chapters_succeeded':True,'source':'recorded running browser console; published Agentforce live actions; actual product APIs','edit':'Cloud waiting compressed; source response inspection retained','duration':re.search(r'Duration: ([0-9:.]+)',probe)[1],'video_h264':'h264' in probe,'audio_aac':'aac' in probe,'captions':'mov_text' in probe,'narration':'macOS Samantha synthetic voice','width':1920,'height':1080,'chapter_count':probe.count('Chapter #')}
decode=subprocess.run([FF,'-v','error','-i',str(target),'-f','null','-'],capture_output=True,text=True)
verify['complete_decode_passed']=decode.returncode==0 and not decode.stderr.strip()
(OUT/'verification.json').write_text(json.dumps(verify,indent=2)+'\n')
print(json.dumps(verify),flush=True)
