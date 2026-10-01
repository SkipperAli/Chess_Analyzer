/**
 * Chess.js-compatible engine (minimal, reliable)
 * Supports: legal move gen, FEN, move/undo, check/checkmate/stalemate
 */
function Chess(fen_str) {
  const DEFAULT_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
  const OFFBOARD = 99, EMPTY = 0;
  const wP=1,wN=2,wB=3,wR=4,wQ=5,wK=6,bP=7,bN=8,bB=9,bR=10,bQ=11,bK=12;
  const PCHAR={P:wP,N:wN,B:wB,R:wR,Q:wQ,K:wK,p:bP,n:bN,b:bB,r:bR,q:bQ,k:bK};
  const CPIECE={}; Object.entries(PCHAR).forEach(([c,v])=>CPIECE[v]=c);
  const COLOR=p=>p===EMPTY?null:p<=6?'w':'b';
  const TYPE=p=>{if(!p)return null;const t=p<=6?p:p-6;return['','p','n','b','r','q','k'][t];};
  
  // 10x12 mailbox
  // rank 8 -> row 2, rank 1 -> row 9; rows 0,1,10,11 and cols 0,9 are padding
  function SQ(f,r){return(10-r)*10+f+1;}
  function SQN(s){const f=(s-1)%10,r=10-Math.floor((s-1)/10);if(f<0||f>7||r<1||r>8)return null;return'abcdefgh'[f]+r;}
  function NS(n){if(!n||n.length<2)return -1;const f='abcdefgh'.indexOf(n[0]),r=parseInt(n[1]);return(f<0||r<1||r>8)?-1:SQ(f,r);}
  
  const KN_OFF=[-21,-19,-12,-8,8,12,19,21];
  const BI_OFF=[-11,-9,9,11], RK_OFF=[-10,-1,1,10], QK_OFF=[-11,-10,-9,-1,1,9,10,11];
  
  let board,turn,cas,ep,hm,fm,hist,posKeys;
  
  function setup(fen){
    board=new Array(120).fill(OFFBOARD);
    for(let r=1;r<=8;r++)for(let f=0;f<8;f++)board[SQ(f,r)]=EMPTY;
    const p=fen.trim().split(/\s+/);
    const rows=p[0].split('/');
    for(let r=0;r<8;r++){let f=0;for(const c of rows[r]){if(c>='1'&&c<='8')f+=+c;else{board[SQ(f,8-r)]=PCHAR[c]||EMPTY;f++;}}}
    turn=p[1]==='b'?'b':'w';
    const cs=p[2]||'-';
    cas={K:cs.includes('K'),Q:cs.includes('Q'),k:cs.includes('k'),q:cs.includes('q')};
    ep=p[3]&&p[3]!=='-'?NS(p[3]):-1;
    hm=+p[4]||0; fm=+p[5]||1; hist=[]; posKeys=[posKey()];
  }

  function posKey(){return getFEN().split(' ').slice(0,4).join(' ');}

  function insufficient(){
    const minors={w:[],b:[]};
    for(let r=1;r<=8;r++)for(let f=0;f<8;f++){
      const p=board[SQ(f,r)];if(p===EMPTY)continue;
      const t=TYPE(p);if(t==='k')continue;
      if(t==='p'||t==='r'||t==='q')return false;
      minors[COLOR(p)].push({t,sqc:(f+r)%2});
    }
    const all=minors.w.concat(minors.b);
    if(all.length<=1)return true;
    // only bishops, all on the same square colour
    return all.every(m=>m.t==='b')&&all.every(m=>m.sqc===all[0].sqc);
  }
  function threefold(){const k=posKeys[posKeys.length-1];return posKeys.filter(x=>x===k).length>=3;}
  
  function getFEN(){
    let out='',em=0;
    for(let r=8;r>=1;r--){for(let f=0;f<8;f++){const p=board[SQ(f,r)];if(p===EMPTY)em++;else{if(em){out+=em;em=0;}out+=CPIECE[p];}}if(em){out+=em;em=0;}if(r>1)out+='/';}
    const cs=(cas.K?'K':'')+(cas.Q?'Q':'')+(cas.k?'k':'')+(cas.q?'q':'')||'-';
    // only write the ep square when a pawn can actually capture there (matches python-chess)
    let eps='-';
    if(ep>0){const pw=turn==='w'?wP:bP,o=turn==='w'?[9,11]:[-9,-11];if(o.some(x=>board[ep+x]===pw))eps=SQN(ep);}
    return`${out} ${turn} ${cs} ${eps} ${hm} ${fm}`;
  }
  
  function attacked(s,byC){
    const opp=byC;
    const pawn=opp==='w'?wP:bP,pOffs=opp==='w'?[9,11]:[-9,-11];
    for(const o of pOffs)if(board[s+o]===pawn)return true;
    const kn=opp==='w'?wN:bN;
    for(const o of KN_OFF)if(board[s+o]===kn)return true;
    const kg=opp==='w'?wK:bK;
    for(const o of QK_OFF)if(board[s+o]===kg)return true;
    const bi=opp==='w'?wB:bB,rk=opp==='w'?wR:bR,qu=opp==='w'?wQ:bQ;
    for(const o of BI_OFF){let t=s+o;while(board[t]!==OFFBOARD){if(board[t]!==EMPTY){if(board[t]===bi||board[t]===qu)return true;break;}t+=o;}}
    for(const o of RK_OFF){let t=s+o;while(board[t]!==OFFBOARD){if(board[t]!==EMPTY){if(board[t]===rk||board[t]===qu)return true;break;}t+=o;}}
    return false;
  }
  
  function kingSquare(c){const kg=c==='w'?wK:bK;for(let r=1;r<=8;r++)for(let f=0;f<8;f++){const s=SQ(f,r);if(board[s]===kg)return s;}return -1;}
  function inCheck(c){return attacked(kingSquare(c),c==='w'?'b':'w');}
  
  function pseudo(c){
    const opp=c==='w'?'b':'w', moves=[];
    function add(from,to,flags,promo){moves.push({from:SQN(from),to:SQN(to),flags:flags||0,promotion:promo||null,piece:TYPE(board[from]),color:c,captured:board[to]!==EMPTY&&board[to]!==OFFBOARD?TYPE(board[to]):null});}
    for(let r=1;r<=8;r++)for(let f=0;f<8;f++){
      const s=SQ(f,r),p=board[s];
      if(p===EMPTY||COLOR(p)!==c)continue;
      const t=TYPE(p);
      if(t==='p'){
        const dir=c==='w'?1:-1,sr=c==='w'?2:7,pr=c==='w'?8:1,fwd=SQ(f,r+dir);
        if(board[fwd]===EMPTY){
          if(r+dir===pr)['q','r','b','n'].forEach(x=>add(s,fwd,16,x));
          else{add(s,fwd,1);if(r===sr&&board[SQ(f,r+2*dir)]===EMPTY)add(s,SQ(f,r+2*dir),2);}
        }
        for(const df of[-1,1]){if(f+df<0||f+df>7)continue;const cs=SQ(f+df,r+dir);if(board[cs]===OFFBOARD)continue;if(board[cs]!==EMPTY&&COLOR(board[cs])===opp){if(r+dir===pr)['q','r','b','n'].forEach(x=>add(s,cs,20,x));else add(s,cs,4);}else if(cs===ep){add(s,cs,8);moves[moves.length-1].captured='p';}}
      } else if(t==='n'){
        for(const o of KN_OFF){const to=s+o;if(board[to]===OFFBOARD)continue;if(board[to]===EMPTY)add(s,to,1);else if(COLOR(board[to])===opp)add(s,to,4);}
      } else if(t==='k'){
        for(const o of QK_OFF){const to=s+o;if(board[to]===OFFBOARD)continue;if(board[to]===EMPTY)add(s,to,1);else if(COLOR(board[to])===opp)add(s,to,4);}
        if(c==='w'&&s===NS('e1')){if(cas.K&&board[NS('f1')]===EMPTY&&board[NS('g1')]===EMPTY&&!attacked(NS('e1'),'b')&&!attacked(NS('f1'),'b')&&!attacked(NS('g1'),'b'))add(s,NS('g1'),32);if(cas.Q&&board[NS('d1')]===EMPTY&&board[NS('c1')]===EMPTY&&board[NS('b1')]===EMPTY&&!attacked(NS('e1'),'b')&&!attacked(NS('d1'),'b')&&!attacked(NS('c1'),'b'))add(s,NS('c1'),64);}
        if(c==='b'&&s===NS('e8')){if(cas.k&&board[NS('f8')]===EMPTY&&board[NS('g8')]===EMPTY&&!attacked(NS('e8'),'w')&&!attacked(NS('f8'),'w')&&!attacked(NS('g8'),'w'))add(s,NS('g8'),32);if(cas.q&&board[NS('d8')]===EMPTY&&board[NS('c8')]===EMPTY&&board[NS('b8')]===EMPTY&&!attacked(NS('e8'),'w')&&!attacked(NS('d8'),'w')&&!attacked(NS('c8'),'w'))add(s,NS('c8'),64);}
      } else {
        const offs=t==='b'?BI_OFF:t==='r'?RK_OFF:QK_OFF;
        for(const o of offs){let to=s+o;while(board[to]!==OFFBOARD){if(board[to]===EMPTY)add(s,to,1);else{if(COLOR(board[to])===opp)add(s,to,4);break;}to+=o;}}
      }
    }
    return moves;
  }
  
  function snap(){return{board:board.slice(),cas:{...cas},ep,hm,fm,turn};}
  function restore(sn){board=sn.board.slice();cas={...sn.cas};ep=sn.ep;hm=sn.hm;fm=sn.fm;turn=sn.turn;}
  
  function apply(m,sn){
    const fr=NS(m.from),to=NS(m.to),c=sn.turn,p=board[fr];
    board[to]=p; board[fr]=EMPTY;
    if(m.promotion){const pm={q:c==='w'?wQ:bQ,r:c==='w'?wR:bR,b:c==='w'?wB:bB,n:c==='w'?wN:bN};board[to]=pm[m.promotion];}
    if(m.flags===8){board[to+(c==='w'?10:-10)]=EMPTY;}
    if(m.flags===32){if(c==='w'){board[NS('f1')]=wR;board[NS('h1')]=EMPTY;}else{board[NS('f8')]=bR;board[NS('h8')]=EMPTY;}}
    if(m.flags===64){if(c==='w'){board[NS('d1')]=wR;board[NS('a1')]=EMPTY;}else{board[NS('d8')]=bR;board[NS('a8')]=EMPTY;}}
    ep=m.flags===2?(to+(c==='w'?10:-10)):-1;
    if(TYPE(p)==='k'){if(c==='w'){cas.K=false;cas.Q=false;}else{cas.k=false;cas.q=false;}}
    if(fr===NS('h1')||to===NS('h1'))cas.K=false;if(fr===NS('a1')||to===NS('a1'))cas.Q=false;
    if(fr===NS('h8')||to===NS('h8'))cas.k=false;if(fr===NS('a8')||to===NS('a8'))cas.q=false;
    hm=(TYPE(p)==='p'||m.captured)?0:hm+1;if(c==='b')fm++;turn=c==='w'?'b':'w';
  }
  
  function legal(opts){
    const ps=pseudo(turn),out=[];
    for(const m of ps){
      const sn=snap();apply(m,sn);
      const ok=!inCheck(sn.turn);
      restore(sn);
      if(ok)out.push(m);
    }
    if(opts&&opts.square)return out.filter(m=>m.from===opts.square).map(m=>opts.verbose?m:m.to);
    if(opts&&opts.verbose)return out;
    return out.map(m=>m.from+m.to+(m.promotion||''));
  }
  
  function makeSAN(m,lv){
    if(m.flags===32)return'O-O';if(m.flags===64)return'O-O-O';
    let s='';
    if(m.piece!=='p'){
      s=m.piece.toUpperCase();
      const amb=lv.filter(x=>x.piece===m.piece&&x.to===m.to&&x.from!==m.from);
      if(amb.length>0){if(!amb.find(x=>x.from[0]===m.from[0]))s+=m.from[0];else if(!amb.find(x=>x.from[1]===m.from[1]))s+=m.from[1];else s+=m.from;}
    }
    if(m.captured||(m.piece==='p'&&m.flags===8)){if(m.piece==='p')s+=m.from[0];s+='x';}
    s+=m.to;if(m.promotion)s+='='+m.promotion.toUpperCase();
    return s;
  }
  
  setup(fen_str||DEFAULT_FEN);
  
  return{
    fen:()=>getFEN(),
    turn:()=>turn,
    get:(n)=>{const s=NS(n);if(s<0||board[s]===EMPTY||board[s]===OFFBOARD)return null;return{type:TYPE(board[s]),color:COLOR(board[s])};},
    moves:(opts)=>legal(opts),
    move:function(input){
      const lv=legal({verbose:true});
      let found=null;
      if(typeof input==='string'){
        found=lv.find(m=>(m.from+m.to+(m.promotion||''))===input);
        if(!found){
          const san=input.replace(/[+#]/,'');
          found=lv.find(m=>{const s=makeSAN(m,lv);return s===san||s===input;});
        }
        if(!found&&(input==='O-O'||input==='0-0'))found=lv.find(m=>m.flags===32);
        if(!found&&(input==='O-O-O'||input==='0-0-0'))found=lv.find(m=>m.flags===64);
      } else {
        found=lv.find(m=>m.from===input.from&&m.to===input.to&&(!input.promotion||m.promotion===input.promotion));
        if(!found&&input.from&&input.to)found=lv.find(m=>m.from===input.from&&m.to===input.to);
      }
      if(!found)return null;
      const sn=snap();apply(found,sn);
      const newLv=legal({verbose:true});
      const ck=inCheck(turn);
      const sfx=ck?(newLv.length===0?'#':'+'):'';
      const san=makeSAN(found,lv)+sfx;
      const res={...found,san};
      hist.push({sn,move:res});
      posKeys.push(posKey());
      return res;
    },
    undo:function(){if(!hist.length)return null;const last=hist.pop();posKeys.pop();restore(last.sn);return last.move;},
    in_check:()=>inCheck(turn),
    in_checkmate:()=>inCheck(turn)&&legal(null).length===0,
    in_stalemate:()=>!inCheck(turn)&&legal(null).length===0,
    insufficient_material:()=>insufficient(),
    in_threefold_repetition:()=>threefold(),
    in_draw:()=>hm>=100||insufficient()||threefold(),
    game_over:function(){return this.in_checkmate()||this.in_stalemate()||this.in_draw();},
    load:(f)=>setup(f),
    reset:()=>setup(DEFAULT_FEN),
    history:()=>hist.map(h=>h.move),
  };
}
if(typeof module!=='undefined')module.exports=Chess;
