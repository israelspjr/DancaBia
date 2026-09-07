import React, {useEffect, useRef, useState} from "react";
import {createRoot} from "react-dom/client";
import "./style.css";

const NOTES = ["DÓ","DÓ♯","RÉ","RÉ♯","MI","FÁ","FÁ♯","SOL","LÁ","SI"];
const KEYS = ["1","2","3","4","5","6","7","8","9","0"];

function App(){
  const [songs,setSongs]=useState([]), [selected,setSelected]=useState("");
  const [lights,setLights]=useState(Array(10).fill("off"));
  const [score,setScore]=useState(0), [combo,setCombo]=useState(0);
  const [status,setStatus]=useState("Escolha uma música"), [result,setResult]=useState(null);
  const ws=useRef(null);
  const audio=useRef(new Audio());

  const paint=(button,color)=>setLights(old=>old.map((v,i)=>i===button?color:v));
  const press=(button)=>{ if(ws.current?.readyState===1) ws.current.send(JSON.stringify({type:"press",button})); };

  useEffect(()=>{
    fetch("/api/songs").then(r=>r.json()).then(data=>{setSongs(data); if(data[0]) setSelected(data[0].id)});
    const socket=new WebSocket(`${location.protocol==="https:"?"wss":"ws"}://${location.host}/ws`); ws.current=socket;
    socket.onmessage=({data})=>{
      const m=JSON.parse(data);
      if(m.type==="countdown") setStatus(String(m.value));
      if(m.type==="started"){setStatus("VALENDO!"); setScore(0); setCombo(0); setResult(null); if(m.audio){audio.current.src=m.audio;audio.current.currentTime=0;audio.current.muted=false;audio.current.play().catch(()=>setStatus("ÁUDIO BLOQUEADO PELO NAVEGADOR"))}}
      if(m.type==="note") paint(m.button,"blue");
      if(m.type==="note_off") paint(m.button,"off");
      if(m.type==="feedback" && m.result==="hit"){paint(m.button,"green");setScore(m.score);setCombo(m.combo);setStatus(`+${m.points}`)}
      if(m.type==="feedback" && m.result==="wrong"){paint(m.button,"red");setStatus("BOTÃO ERRADO")}
      if(m.type==="feedback" && m.result==="miss"){paint(m.button,"red");setCombo(0);setStatus("PERDEU A NOTA")}
      if(m.type==="finished"){audio.current.pause();setLights(Array(10).fill("off"));setStatus("RODADA FINALIZADA");setResult(m)}
      if(m.type==="stopped") audio.current.pause();
      if(m.type==="system_test_started") setStatus("TESTE DE SISTEMA: acendendo as 10 ilhas...");
      if(m.type==="system_test_finished"){setLights(Array(10).fill("off"));setStatus("TESTE DE SISTEMA CONCLUÍDO");}
    };
    const keydown=e=>{const i=KEYS.indexOf(e.key); if(i>=0 && !e.repeat) press(i)};
    addEventListener("keydown",keydown); return()=>{removeEventListener("keydown",keydown);socket.close()};
  },[]);

  const start=()=>{const song=songs.find(item=>item.id===selected);if(song?.audio){audio.current.src=song.audio;audio.current.muted=true;audio.current.play().catch(()=>{});}ws.current?.send(JSON.stringify({type:"start",song:selected}))};
  const systemTest=async()=>{setStatus("TESTE DE SISTEMA: iniciando...");const r=await fetch("/api/system-test",{method:"POST"});if(!r.ok){const d=await r.json().catch(()=>({}));setStatus(d.detail||"Não foi possível iniciar o teste de sistema")}};
  if(location.pathname==="/inserir_musica") return <Admin songs={songs} reload={()=>fetch("/api/songs").then(r=>r.json()).then(setSongs)}/>;
  return <main>
    <header><div><small>RASPBERRY PI 5</small><h1>DESAFIO MUSICAL</h1></div><div className="score"><span>PONTOS</span><b>{score}</b><span>COMBO × {combo}</span></div></header>
    <section className="panel">
      <label>MÚSICA</label><select value={selected} onChange={e=>setSelected(e.target.value)}>{songs.map(s=><option key={s.id} value={s.id}>{s.title}</option>)}</select>
      <button className="start" onClick={start} disabled={!selected}>INICIAR RODADA</button>
      <button className="systest" onClick={systemTest} type="button">TESTE DE SISTEMA</button>
    </section>
    <div className="status">{status}</div>
    <section className="buttons">{NOTES.map((note,i)=><button key={note} className={`music ${lights[i]}`} onPointerDown={()=>press(i)}><span>{KEYS[i]}</span><b>{note}</b></button>)}</section>
    {result&&<section className="result"><h2>Resultado</h2><b>{result.score} pontos</b><p>{result.hits} acertos · {result.misses} erros · {result.total} notas</p></section>}
    <footer>Painel físico ativo · teclas 1 a 0 para teste · <a href="/inserir_musica">Administrar músicas</a></footer>
  </main>
}

function Admin({songs,reload}){
  const example=`[\n  {"time_ms": 1000, "button": 0, "note": "DO", "window_ms": 450},\n  {"time_ms": 2200, "button": 2, "note": "RE", "window_ms": 450}\n]`;
  const [message,setMessage]=useState(""),[events,setEvents]=useState([]),[editingId,setEditingId]=useState(""),[mode,setMode]=useState("automatic");
  const submit=async e=>{
    e.preventDefault();const form=e.currentTarget;setMessage(mode==="youtube"?"Baixando do YouTube e analisando. Pode levar alguns minutos no Raspberry...":"Analisando o MP3. Isso pode levar alguns minutos no Raspberry...");
    const response=await fetch("/api/songs",{method:"POST",body:new FormData(form)});
    const data=await response.json();
    if(!response.ok){setMessage(data.detail||"Falha no envio");return}
    setMessage(`Música “${data.song.title}” adicionada com ${data.events.length} notas.`);setEvents(data.events);setEditingId(data.song.id);form.reset();reload();
  };
  const editSong=async id=>{const data=await fetch(`/api/songs/${id}`).then(r=>r.json());setEvents(data.events||[]);setEditingId(id);setMessage(`Editando ${data.title}`)};
  const updateEvent=(index,key,value)=>setEvents(old=>old.map((event,i)=>i===index?{...event,[key]:Number(value)}:event));
  const removeEvent=index=>setEvents(old=>old.filter((_,i)=>i!==index));
  const saveChart=async()=>{const response=await fetch(`/api/songs/${editingId}/chart`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(events)});const data=await response.json();setMessage(response.ok?`Mapa salvo com ${data.events.length} notas.`:(data.detail||"Erro ao salvar"));reload()};
  return <main className="admin">
    <header><div><small>ADMINISTRATIVO</small><h1>INSERIR MÚSICA</h1></div><a className="back" href="/">← Voltar ao jogo</a></header>
    <section className="adminGrid">
      <form className="upload" onSubmit={submit}>
        <label>TÍTULO</label><input name="title" required placeholder="Nome da música"/>
        <label>ARTISTA</label><input name="artist" placeholder="Nome do artista"/>
        <label>GERAÇÃO DO MAPA</label><select name="generation_mode" value={mode} onChange={e=>setMode(e.target.value)}><option value="automatic">Upload MP3 — mapa automático</option><option value="youtube">Link do YouTube — mapa automático</option><option value="manual">Upload MP3 — colar mapa JSON</option></select>
        {mode==="youtube"
          ? <><label>LINK DO YOUTUBE</label><input name="youtube_url" type="url" placeholder="https://www.youtube.com/watch?v=..." required/><p className="hint">Uso educacional interno (Senac SP). Requer internet no momento do cadastro.</p></>
          : <><label>ARQUIVO MP3</label><input name="audio" type="file" accept="audio/mpeg,.mp3" required/></>}
        <label>DIFICULDADE</label><select name="difficulty" defaultValue="medium"><option value="easy">Fácil — menos notas</option><option value="medium">Média</option><option value="hard">Difícil — mais notas</option></select>
        <label>MÁXIMO DE NOTAS</label><input name="max_notes" type="number" min="10" max="2000" defaultValue="350"/>
        <details><summary>Mapa manual (opcional)</summary><textarea name="chart_json" defaultValue={example}/></details>
        <p className="hint">O Python detecta ataques e escolhe a nota cromática predominante. Depois você pode corrigir cada tempo e botão na tabela.</p>
        <button className="start">SALVAR E PROCESSAR</button><strong className="message">{message}</strong>
      </form>
      <section className="songList"><h2>Músicas cadastradas</h2>{songs.map(s=><article key={s.id}><b>{s.title}</b><span>{s.artist||"Sem artista"} · {s.event_count} notas</span><button onClick={()=>editSong(s.id)}>Ver/editar notas</button></article>)}</section>
    </section>
    {events.length>0&&<section className="chartEditor"><div className="editorTitle"><h2>Notas e tempos gerados</h2><button className="start" onClick={saveChart}>SALVAR AJUSTES</button></div><div className="tableWrap"><table><thead><tr><th>#</th><th>Tempo (ms)</th><th>Botão</th><th>Nota</th><th>Janela</th><th>Confiança</th><th></th></tr></thead><tbody>{events.map((event,i)=><tr key={i}><td>{i+1}</td><td><input type="number" value={event.time_ms} onChange={e=>updateEvent(i,"time_ms",e.target.value)}/></td><td><input type="number" min="0" max="9" value={event.button} onChange={e=>updateEvent(i,"button",e.target.value)}/></td><td>{NOTES[event.button]||event.note}</td><td><input type="number" value={event.window_ms||430} onChange={e=>updateEvent(i,"window_ms",e.target.value)}/></td><td>{event.confidence??"—"}</td><td><button className="remove" onClick={()=>removeEvent(i)}>×</button></td></tr>)}</tbody></table></div></section>}
  </main>
}
createRoot(document.getElementById("root")).render(<App/>);
