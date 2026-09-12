// npm install playwright && npx playwright install chromium
// python serve.py --no-open ; node tools/capture_video.js (in a second terminal)
// FPS, URL, OUT, CHROME_PATH may be supplied through environment variables.
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const FPS=Number(process.env.FPS||30);
const OUT=process.env.OUT||path.join(__dirname,'..','frames-'+new Date().toISOString().replace(/[:.]/g,'-'));
const URL=process.env.URL||'http://127.0.0.1:8765/?capture=1';
(async()=>{
  if(!Number.isFinite(FPS)||FPS<=0||FPS>120)throw Error('FPS must be in (0, 120]');
  if(fs.existsSync(OUT)&&fs.readdirSync(OUT).length)throw Error('OUT must be empty: '+OUT);
  fs.mkdirSync(OUT,{recursive:true});
  const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:900},deviceScaleFactor:1});
    let pageError=null;page.on('pageerror',e=>{pageError=e;});
    await page.goto(URL,{waitUntil:'load'});
    await page.waitForFunction(()=>!!window.capture,null,{timeout:60000});
    const duration=await page.evaluate(()=>window.capture.duration),count=Math.ceil(duration*FPS);
    const manifest=await page.evaluate(()=>({duration:window.capture.duration,shots:window.capture.shots}));
    fs.writeFileSync(path.join(OUT,'shots.json'),JSON.stringify({...manifest,FPS,URL},null,2));
    for(let frame=0;frame<count;frame++){
      if(pageError)throw pageError;
      await page.evaluate(([time,fps])=>window.capture.renderAt(time,fps),[frame/FPS,FPS]);
      // A fresh screenshot after each render; never reuse a stale screencast frame.
      await page.screenshot({path:path.join(OUT,'f'+String(frame).padStart(5,'0')+'.jpg'),type:'jpeg',quality:90});
      if(frame%100===0)console.log(`${frame}/${count}`);
    }
    console.log(`Frames: ${OUT}\nEncode: ffmpeg -framerate ${FPS} -i "${path.join(OUT,'f%05d.jpg')}" -c:v libx264 -crf 22 -pix_fmt yuv420p out.mp4`);
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

