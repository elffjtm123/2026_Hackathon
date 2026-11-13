export type Landmark = {x: number; y: number};
export type PulseRegion = {name: string; x: number; y: number; width: number; height: number; valid: boolean};

// Anatomical centres + eye-distance-scaled areas, not bounding boxes of almost
// collinear landmarks (the old forehead points could be <4 pixels tall).
export function pulseRegions(face: Landmark[], width: number, height: number): PulseRegion[] {
  if (face.length < 468 || width <= 0 || height <= 0) return [];
  const eye = Math.hypot((face[263].x - face[33].x) * width, (face[263].y - face[33].y) * height);
  if (!Number.isFinite(eye) || eye < 24) return [];
  const centres = [
    {name: '이마', x: face[10].x * 0.4 + face[168].x * 0.6,
      y: face[10].y * 0.4 + face[168].y * 0.6, w: 0.58, h: 0.24},
    {name: '왼볼', x: face[50].x * 0.55 + face[101].x * 0.45,
      y: face[50].y * 0.55 + face[101].y * 0.45, w: 0.28, h: 0.26},
    {name: '오른볼', x: face[280].x * 0.55 + face[330].x * 0.45,
      y: face[280].y * 0.55 + face[330].y * 0.45, w: 0.28, h: 0.26},
  ];
  return centres.map(c => {
    const desiredWidth = Math.round(eye * c.w), desiredHeight = Math.round(eye * c.h);
    const left = Math.round(c.x * width - desiredWidth / 2), top = Math.round(c.y * height - desiredHeight / 2);
    const x = Math.max(0, Math.min(width, left)), y = Math.max(0, Math.min(height, top));
    const w = Math.max(0, Math.min(width, left + desiredWidth) - x);
    const h = Math.max(0, Math.min(height, top + desiredHeight) - y);
    const valid = [x, y, w, h].every(Number.isFinite) && w >= 4 && h >= 4 && w * h >= 36
      && w * h >= desiredWidth * desiredHeight * 0.9;
    return {name: c.name, x: x / width, y: y / height, width: w / width, height: h / height, valid};
  });
}

export type FaceCaptureAssessment = {
  crop: {x:number; y:number; side:number} | null;
  reason: string; warning: string; eyePixels:number; faceWidth:number; faceHeight:number;
};

// Neural models use a whole face crop. A small eye-distance ratio or a moderate
// pose is not by itself a reason to reject all frames (POS has separate gates).
export class FaceCropTracker {
  previous: {x:number; y:number; side:number} | null = null;
  lastTime = -Infinity;
  last: FaceCaptureAssessment | null = null;
  reset() { this.previous=null; this.last=null; this.lastTime=-Infinity; }
  update(face: Landmark[], width:number, height:number, detectionTime:number): FaceCaptureAssessment {
    if (detectionTime === this.lastTime && this.last) return this.last;
    const invalid = (reason:string, eyePixels=0, faceWidth=0, faceHeight=0): FaceCaptureAssessment => {
      this.previous=null;
      return this.last={crop:null,reason,warning:'',eyePixels,faceWidth,faceHeight};
    };
    this.lastTime=detectionTime;
    if (face.length<468 || face.slice(0,468).some(p=>!Number.isFinite(p.x)||!Number.isFinite(p.y)))
      return invalid('얼굴 위치를 계산할 수 없습니다.');
    const xs=face.slice(0,468).map(p=>p.x*width), ys=face.slice(0,468).map(p=>p.y*height);
    const minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
    const fw=maxX-minX,fh=maxY-minY;
    const dx=(face[263].x-face[33].x)*width,dy=(face[263].y-face[33].y)*height;
    const eye=Math.hypot(dx,dy);
    if (eye<20 || fw<40 || fh<48) return invalid(`얼굴 해상도 부족 · 눈 사이 ${eye.toFixed(0)}px, 얼굴 ${fw.toFixed(0)}×${fh.toFixed(0)}px`,eye,fw,fh);
    const visibleW=Math.max(0,Math.min(width,maxX)-Math.max(0,minX));
    const visibleH=Math.max(0,Math.min(height,maxY)-Math.max(0,minY));
    if (visibleW*visibleH/(fw*fh)<.75) return invalid('얼굴의 상당 부분이 화면 밖입니다.',eye,fw,fh);
    const raw={x:(minX+maxX)/2,y:(minY+maxY)/2,side:Math.min(width,height,Math.max(fw,fh)*1.5)};
    const previous=this.previous;
    const motion=previous ? Math.hypot(raw.x-previous.x,raw.y-previous.y)/previous.side : 0;
    if (motion>.65 || previous && Math.abs(raw.side-previous.side)/previous.side>.6)
      return invalid('얼굴 위치가 크게 바뀌어 새 영상 구간을 수집합니다.',eye,fw,fh);
    const stabilized=previous ? {x:previous.x*.35+raw.x*.65,y:previous.y*.35+raw.y*.65,side:previous.side*.8+raw.side*.2} : raw;
    this.previous=stabilized;
    const yawProxy=Math.abs(face[1].x*width-(face[33].x+face[263].x)*width/2)/eye;
    const warning=motion>.08 || Math.abs(dy)/eye>.3 || yawProxy>.3 ? '얼굴 움직임·각도 변화 있음 · 신호 품질을 확인하며 분석 중' : '';
    return this.last={crop:{x:Math.max(0,Math.min(width-stabilized.side,stabilized.x-stabilized.side/2)),
      y:Math.max(0,Math.min(height-stabilized.side,stabilized.y-stabilized.side/2)),side:stabilized.side},
      reason:'',warning,eyePixels:eye,faceWidth:fw,faceHeight:fh};
  }
}
