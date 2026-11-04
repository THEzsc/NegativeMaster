/* Display-space geometry and selection, shared with browser regression tests. */
(function(root){
  function orient(source,operation){
    const p=JSON.parse(JSON.stringify(source)),mirrored=['h','v'].includes(p.flip);
    const swap=['cw','ccw'].includes(operation);
    const point=([x,y])=>({cw:[1-y,x],ccw:[y,1-x],h:[1-x,y],v:[x,1-y]})[operation];
    let rotation=Number(p.rotate)||0;
    if(swap)rotation+=(operation==='cw'?90:-90)*(mirrored?-1:1);
    else {if(p.flip===operation)p.flip='none';else if(!mirrored)p.flip=operation;else{p.flip='none';rotation+=180;}p.level_angle=-(Number(p.level_angle)||0);}
    p.rotate=(rotation%360+360)%360;
    for(const key of ['crop_rect','wb_rect','film_base_rect','shadow_rect','highlight_rect']){
      const v=p[key];if(!v)continue;const a=Array.isArray(v)?v:[v.x0,v.y0,v.x1,v.y1];
      const b=point(a.slice(0,2)),c=point(a.slice(2));const r=[Math.min(b[0],c[0]),Math.min(b[1],c[1]),Math.max(b[0],c[0]),Math.max(b[1],c[1])];
      p[key]=Array.isArray(v)?r:Object.assign(v,Object.fromEntries(['x0','y0','x1','y1'].map((k,i)=>[k,r[i]])));
    }
    if(p.wb_point?.length===2)p.wb_point=point(p.wb_point);
    p.geometry_source='manual';return p;
  }
  function selection(paths,selected,anchor,path,shift,toggle){
    const result=new Set(toggle?selected:[]),i=paths.indexOf(path),j=paths.indexOf(anchor);
    if(shift&&i>=0&&j>=0)paths.slice(Math.min(i,j),Math.max(i,j)+1).forEach(p=>result.add(p));
    else if(toggle&&result.has(path))result.delete(path);else result.add(path);
    return [...result];
  }
  function gammaPatch(report){return report&&Number.isFinite(report.recommendation)&&['gamma','nd_gamma'].includes(report.parameter_key)&&['high','medium'].includes(report.confidence)&&report.recommendation>=(report.parameter_key==='gamma'?.6:1)&&report.recommendation<=(report.parameter_key==='gamma'?3:8)?{[report.parameter_key]:report.recommendation}:null;}
  const api={orient,selection,gammaPatch};if(typeof module!=='undefined')module.exports=api;else root.NMDevelopModel=api;
})(typeof globalThis!=='undefined'?globalThis:this);
