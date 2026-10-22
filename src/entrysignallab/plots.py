"""Export publication figures and a portable local report. MIT License."""
from pathlib import Path
import csv, html, json, io, tempfile
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from .model import demand, STRATEGIES, payoff, payoff_grid, finite_number, decisions

def resolve_plot_settings(p,bounds,rival,spec=None):
    """Validate reference controls and disclose a finite visualization window."""
    spec = {} if spec is None else spec
    if not isinstance(spec,dict) or set(spec)-{"announcement","delay","surface_announcement_max"}:
        raise ValueError("plot must be an object with announcement, delay or surface_announcement_max")
    lo,hi=bounds.validate(p);cap=bounds.announcement_upper
    rival=finite_number(rival,'rival_delay',minimum=0)
    if rival>p.growth_end:raise ValueError('rival_delay exceeds growth_end')
    intensity=finite_number(spec.get("announcement",min(.2,cap) if cap is not None else .2),"plot announcement",minimum=0)
    if cap is not None and intensity>cap: raise ValueError("plot announcement exceeds the decision bound")
    delay=finite_number(spec.get("delay",min(hi,max(lo,rival))),"plot delay",minimum=0)
    if not lo<=delay<=hi: raise ValueError("plot follower delay is outside the decision bounds")
    window=finite_number(spec.get("surface_announcement_max",cap if cap is not None else 2.),"surface_announcement_max",minimum=0)
    if cap is not None and window>cap: raise ValueError("surface window exceeds the announcement bound")
    controls={st:{"delay":rival if st.endswith("F") else delay,"announcement":intensity if st.startswith("R") else 0.} for st in STRATEGIES}
    return {"trajectory_controls":controls,"surface_announcement_max":window,
            "announcement_upper":cap,"surface_is_finite_window":cap is None,
            "interpretation":"Trajectories use the recorded reference controls, not optimized controls. A finite surface window does not bound an unbounded optimization problem."}

def write_csv(path,rows):
    from .workflow import csv_export_row
    if not rows:return
    names=list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=names);writer.writeheader();writer.writerows(csv_export_row(row) for row in rows)

def save_figure(fig,path):
    path=Path(path)
    for extension in ["png","pdf","svg"]:
        buffer=io.BytesIO()
        fig.savefig(buffer,format=extension,dpi=220,bbox_inches="tight",metadata={"Creator":"EntrySignalLab"} if extension=="pdf" else None)
        content=buffer.getvalue()
        if not content:raise OSError(f"empty figure export: {extension}")
        with tempfile.NamedTemporaryFile(dir=path.parent,suffix=".tmp",delete=False) as f:
            f.write(content);temporary=Path(f.name)
        temporary.replace(path.with_suffix("."+extension))
    plt.close(fig)

def trajectories(directory,p,delay=.15,announcement=.2,controls=None):
    delay=min(delay,p.growth_end)
    t=np.unique(np.r_[np.linspace(0,p.horizon,301),delay,p.growth_end])
    fig,axs=plt.subplots(2,2,figsize=(8.2,5.2),sharex=True,sharey=True)
    rows=[]
    for st,ax in zip(STRATEGIES,axs.flat):
        tau=controls[st]["delay"] if controls else delay
        d=controls[st]["announcement"] if controls else announcement if st.startswith("R") else 0
        times=np.unique(np.r_[t,tau]);x,y=demand(p,st,times,tau,d)
        ax.plot(times,x,color="black",lw=1.6,label="Object platform x")
        ax.plot(times,y,color=".5",ls="--",lw=1.5,label="Rival platform y")
        ax.axvline(tau,color=".7",ls=":");ax.axvline(p.growth_end,color=".7",ls=":")
        ax.set_title(f"{st}  delay={tau:g}  intensity={d:g}",fontsize=9);ax.set_xlabel("Time");ax.set_ylabel("Consumer stock");ax.grid(alpha=.15)
        for time,a,b in zip(times,x,y):rows.append({"strategy":st,"time":time,"demand_x":a,"demand_y":b,"delay":tau,"announcement":d})
    axs[0,0].legend(fontsize=8);fig.tight_layout()
    save_figure(fig,Path(directory)/"demand_trajectories");write_csv(Path(directory)/"demand_trajectories.csv",rows)

def profit_surface(directory,p,bounds,settings=None):
    lo,hi=bounds.validate(p);upper=bounds.announcement_upper
    if settings is not None: upper=settings["surface_announcement_max"]
    elif upper is None: raise ValueError("an unbounded problem requires an explicit surface visualization window")
    ts=np.linspace(lo,hi,81);ds=np.linspace(0,upper,81)
    z=payoff_grid(p,"RL",ts,ds)
    fig,ax=plt.subplots(figsize=(6.3,3.5))
    if hi==lo and upper==0:
        value=float(z[0,0])
        ax.scatter([0.],[value],color='black',marker='o',s=35)
        ax.annotate(f'payoff={value:g}',(0.,value),xytext=(7,7),textcoords='offset points',fontsize=8)
        ax.set_xlabel('Announcement intensity');ax.set_ylabel('Object platform net payoff')
        ax.set_title(f'RL point at delay={lo:g}, intensity=0',fontsize=10)
    elif hi==lo or upper==0:
        horizontal=ds if hi==lo else ts
        values=z[:,0] if hi==lo else z[0,:]
        ax.plot(horizontal,values,color="black")
        ax.set_xlabel("Announcement intensity" if hi==lo else "Follower delay")
        ax.set_ylabel("Object platform net payoff")
        ax.set_title(f"RL slice at delay={lo:g}" if hi==lo else "RL slice at intensity=0")
    else:
        c=ax.contourf(ts,ds,z,18,cmap="Greys")
        fig.colorbar(c,ax=ax,label="Object platform net payoff")
        ax.set_xlabel("Follower delay");ax.set_ylabel("Announcement intensity")
        ax.set_title("RL conditional payoff surface"+(f"  window [0, {upper:g}]" if bounds.announcement_upper is None else ""),fontsize=10)
    save_figure(fig,Path(directory)/"rl_payoff_surface")

def sweep_plot(directory,rows,axis,outside_option=0.):
    fig,ax=plt.subplots(figsize=(6.3,3.5))
    for i,st in enumerate(STRATEGIES):
        data=sorted([r for r in rows if r["strategy"]==st],key=lambda r:r[axis])
        values=[r['payoff'] if r['payoff'] is not None else np.nan for r in data]
        coordinates=np.asarray(list(zip([r[axis] for r in data],values)),dtype=float).reshape(-1,2)
        valid=np.isfinite(coordinates).all(axis=1);isolated=[];start=0
        while start<len(data):
            if not valid[start]:
                start+=1;continue
            end=start+1
            while end<len(data) and valid[end]:end+=1
            # A finite run with one unique coordinate has no visible line.
            # Mark its actual point once, preserving every original vertex
            # and every missing-value break in the line data.
            if np.all(coordinates[start:end]==coordinates[start]):isolated.append(start)
            start=end
        ax.plot([r[axis] for r in data],values,color=str(i*.22),
                linestyle=['-','--',':','-.'][i],label=st,
                marker=['o','s','^','x'][i] if isolated else None,markevery=isolated,
                markersize=[8,7,6,6][i],markerfacecolor='none')
    ax.set_xlabel(axis.replace("_"," "));ax.set_ylabel("Conditional net payoff");ax.legend();ax.grid(alpha=.18)
    ax.axhline(outside_option,color=".7",lw=.8,label="Non-entry reference")
    failed={r[axis] for r in rows if r.get("batch_status","ok")!="ok"}
    if failed:ax.scatter(sorted(failed),[.03]*len(failed),transform=ax.get_xaxis_transform(),marker="x",color="black",label="Failed case")
    ax.legend()
    save_figure(fig,Path(directory)/"sensitivity")

def regime_plot(directory,rows,axes):
    if len(axes)!=2:return
    xname,yname=list(axes);x=sorted(set(axes[xname]));y=sorted(set(axes[yname]))
    labels={};legend=list(STRATEGIES)+["tie","unrankable"]
    legend += [kind for kind in ["invalid_configuration","numerical_error"] if any(r.get("batch_status")==kind for r in rows)]
    for r in rows:
        key=(r[xname],r[yname]);best=r["co_best"].split("|") if r["co_best"] else []
        label=r["batch_status"] if r.get("batch_status","ok")!="ok" else "unrankable" if not r["all_rankable"] else best[0] if len(best)==1 else "tie"
        labels[key]=legend.index(label)
    matrix=np.array([[labels[(a,b)] for a in x] for b in y])
    from matplotlib.colors import ListedColormap,BoundaryNorm
    cmap=ListedColormap(["#111111","#555555","#888888","#bbbbbb","#eeeeee","#ffffff"]+(["#ccdddd"] if "invalid_configuration" in legend else [])+(["#ddccdd"] if "numerical_error" in legend else []))
    fig,ax=plt.subplots(figsize=(6.3,3.8))
    norm=BoundaryNorm(np.arange(-.5,len(legend)+.5),len(legend))
    if len(x)==1 or len(y)==1:
        # A nearest mesh has zero-width cells along a singleton dimension.
        # Show the actual sampled coordinates rather than inventing cell area.
        xx,yy=np.meshgrid(x,y)
        im=ax.scatter(xx.ravel(),yy.ravel(),c=matrix.ravel(),marker='s',s=70,
                      edgecolors='black',linewidths=.6,cmap=cmap,norm=norm)
    else:
        im=ax.pcolormesh(x,y,matrix,shading="nearest",cmap=cmap,norm=norm)
    bar=fig.colorbar(im,ax=ax,ticks=range(len(legend)));bar.ax.set_yticklabels(legend)
    for kind,marker in [("invalid_configuration","x"),("numerical_error","+")]:
        points=[key for key,value in labels.items() if legend[value]==kind]
        if points:ax.scatter([a for a,b in points],[b for a,b in points],marker=marker,color="black",s=30)
    ax.set_xlabel(xname.replace("_"," "));ax.set_ylabel(yname.replace("_"," "));ax.set_title("Best conditional scenario at each grid point")
    from matplotlib.ticker import MaxNLocator,ScalarFormatter
    for axis in (ax.xaxis,ax.yaxis):
        axis.set_major_locator(MaxNLocator(5))
        formatter=ScalarFormatter(useOffset=True,useMathText=True)
        formatter.set_scientific(True)
        formatter.set_powerlimits((-3,4))
        axis.set_major_formatter(formatter)
    save_figure(fig,Path(directory)/"strategy_regions")

def _display_disagreements(comparison):
    """Explain observed guard/display differences without re-evaluating the model."""
    values={row['strategy']:row.get('payoff') for row in comparison['results']}
    values['outside_option']=comparison['outside_option_payoff']
    tolerance=comparison['tie_tolerance'];warnings=[]
    for record in comparison.get('comparison_precision',{}).get('refined_comparisons',[]):
        a,b=values.get(record['left']),values.get(record['right'])
        if a is None or b is None:continue
        raw=a-b;sign=(raw>0)-(raw<0)
        relation=1 if raw>tolerance else -1 if raw < -tolerance else 0
        if sign!=record['sign'] or relation!=record['tolerance_relation']:
            warnings.append({**record,'displayed_difference':raw})
    return warnings


def _gap_text(record):
    if record['representation']=='underflow':
        return ('Positive' if record['sign']>0 else 'Negative')+' below display range; log magnitude '+str(record['log_abs'])
    if record['representation']=='outside_float_range':
        return ('Positive' if record['sign']>0 else 'Negative')+' outside display range; log magnitude '+str(record['log_abs'])
    return str(record['value'])


def _probe_record_html(results):
    sections=[]
    def cell(value):return '<td>'+html.escape(str(value))+'</td>'
    def control(value):
        return '<br>'.join(html.escape(name+'='+str(value[name])) for name in ('delay','announcement','payoff'))
    for result in results:
        if not result['strategy'].endswith('L'):continue
        ledger=result.get('local_probe_diagnostics')
        if ledger is None:continue
        text='<details class="local-probe-records" data-strategy="'+html.escape(result['strategy'])+'"><summary>'+html.escape(result['strategy'])+' recorded local probes</summary>'
        text+='<p>Final-control neighborhood: '+html.escape(ledger['status'])+'. Reason: '+html.escape(ledger['reason'].replace('_',' '))+'.</p>'
        if ledger['rounds']:
            text+='<div style="overflow-x:auto"><table><tr>'+''.join('<th>'+name+'</th>' for name in ['Round','Starting control','Lower probe','Upper probe','Selected control','Recorded payoff gain','Payoff threshold','Check'])+'</tr>'
            for record in ledger['rounds']:
                text+='<tr data-probe-round="'+str(record['round'])+'">'+cell(record['round'])
                for value in [record['starting_control'],record['probes'][0]['control'],record['probes'][1]['control'],record['selected_control']]:text+='<td>'+control(value)+'</td>'
                text+=cell(_gap_text(record['improvement_diagnostic']))+cell(record['quality_threshold'])+cell('Passed' if record['passed'] else 'Failed')+'</tr>'
            text+='</table></div><p>A passed gain check after promotion does not assess the new final neighborhood. Coincident controls remain explicitly recorded.</p>'
        else:text+='<p>No finite neighborhood probes were performed for this result.</p>'
        sections.append(text+'</details>')
    return ''.join(sections)


def html_report(directory,comparison,audit=None,plot_settings=None,stability=None):
    rows="".join("<tr>"+"".join(f"<td>{html.escape(str(r.get(k,'')))}</td>" for k in ["strategy","status","delay","announcement","payoff"])+"</tr>" for r in comparison["results"])
    text=f"""<!doctype html><html lang='en'><meta charset='utf-8'><title>EntrySignalLab results</title>
<style>body{{font:16px/1.5 system-ui;max-width:1000px;margin:40px auto;padding:0 24px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px}}img{{max-width:100%}}pre{{white-space:pre-wrap}}</style>
<h1>EntrySignalLab results</h1><p>{html.escape(comparison['interpretation'])}</p>
<table><tr><th>Strategy</th><th>Status</th><th>Delay</th><th>Announcement</th><th>Payoff</th></tr>{rows}</table>
<p>Absolute payoff tie tolerance: {comparison['tie_tolerance']}</p>
<p>Co-best conditional scenarios: {html.escape(', '.join(comparison['co_best']))}</p>
<p>Comparison with the non-entry payoff reference of {comparison['outside_option_payoff']}: {html.escape(', '.join(comparison['preferred_with_outside_option']))}</p>
<p>Gap to the non-entry reference: {comparison['outside_option_gap']}. Near comparisons in the default model use original inputs; the gap can differ from subtracting displayed payoffs.</p>
"""
    discrepancies=_display_disagreements(comparison)
    if discrepancies:
        text+='<section id="payoff-display-warning" data-status="disagreement"><h2>Displayed payoff precision</h2><p>Displayed payoffs are approximate. In this run, original-input comparisons change an ordering or an absolute tie-band decision relative to subtracting those displayed values. Use the guarded gaps for these decisions; this does not establish global optimality.</p>'
        text+='<div style="overflow-x:auto"><table><tr><th>Comparison</th><th>Displayed subtraction</th><th>Guarded gap</th><th>Guarded sign</th><th>Absolute tie band</th><th>Decision basis</th></tr>'
        for record in discrepancies:
            values=[record['left']+' minus '+record['right'],record['displayed_difference'],_gap_text(record),
                    {1:'positive',0:'zero',-1:'negative'}[record['sign']],
                    {1:'above band',0:'within band',-1:'below band'}[record['tolerance_relation']],record['decision_basis']]
            text+='<tr>'+''.join('<td>'+html.escape(str(value))+'</td>' for value in values)+'</tr>'
        text+='</table></div><p>Inspect the complete comparison basis in <a href="comparison.json">comparison.json</a>.</p></section>'
    labels={'pass':'Passed','fail':'Failed','not_assessed':'Not assessed','not_applicable':'Not applicable'}
    quality=comparison.get('local_quality_status','not_assessed')
    notices={'fail':'Warning: at least one local check failed. Review the returned candidates and the detailed diagnostics before interpreting their ranking.',
             'pass':'All four finite candidates passed the recorded local checks.',
             'not_assessed':'Local quality is not fully assessed. A missing or unattained candidate is not a passed check.'}
    text+=f'<section id="numerical-quality" data-status="{html.escape(quality)}"><h2>Numerical quality</h2><p>{html.escape(notices.get(quality,notices["not_assessed"]))}</p>'
    text+='<table><tr><th>Strategy</th><th>Local probe check</th><th>Announcement KKT residual divided by marginal scale</th></tr>'
    for row in comparison['results']:
        status=comparison.get('local_quality_by_strategy',{}).get(row['strategy'],'not_assessed')
        residual=row.get('announcement_stationarity_scaled_residual')
        text+='<tr>'+''.join('<td>'+html.escape(str(value))+'</td>' for value in [row['strategy'],labels.get(status,status),residual if residual is not None else 'Not assessed'])+'</tr>'
    text+='</table><p>Local checks and announcement residuals have different meanings. A passed local check is not a global error bound. Each supplied local_probe_diagnostics record contains the actual per-round controls, gain and payoff threshold in <a href="comparison.json">the numerical diagnostics</a>. Configuration settings are in <a href="config.json">config.json</a>.</p>'
    text+=_probe_record_html(comparison['results'])+'</section>'
    if stability is None:
        text+='<section id="mesh-stability" data-status="not_checked"><h2>Mesh stability</h2><p>Not checked. Enable the stability option to compare returned controls across meshes.</p></section>'
    else:
        assessed=[row for row in stability['strategies'] if row.get('observed_payoff_spread_diagnostic') is not None]
        payoff_status='fail' if any(not row['within_quality_tolerance'] for row in assessed) else 'pass' if len(assessed)==len(stability['strategies']) else 'not_assessed'
        ranking_assessed=all(report['all_rankable'] for report in stability['reports'])
        rank_status=('pass' if stability['ranking_stable'] else 'fail') if ranking_assessed else 'not_assessed'
        words={'pass':'stable','fail':'unstable','not_assessed':'not assessed'}
        text+=f'<section id="mesh-stability" data-status="{payoff_status}"><h2>Mesh stability</h2><p data-check="payoff">Payoff agreement: {words[payoff_status]}.</p><p data-check="ranking">Ranking agreement: {words[rank_status]}.</p>'
        if payoff_status=='fail':text+='<p>Warning: returned payoff values do not agree within the configured tolerance. A stable ranking does not remove this warning.</p>'
        text+='<table><tr><th>Strategy</th><th>Observed payoff spread</th><th>Quality threshold</th><th>Agreement</th></tr>'
        for row in stability['strategies']:
            diagnostic=row.get('observed_payoff_spread_diagnostic')
            state='not_assessed' if diagnostic is None else 'pass' if row['within_quality_tolerance'] else 'fail'
            amount=row['observed_payoff_spread']
            if diagnostic is not None and diagnostic['representation']=='underflow':
                amount='Positive spread below the floating-point display range; log magnitude '+str(diagnostic['log_abs'])
            elif diagnostic is not None and diagnostic['representation']=='outside_float_range':
                amount='Outside the floating-point display range; log magnitude '+str(diagnostic['log_abs'])
            text+='<tr>'+''.join('<td>'+html.escape(str(value))+'</td>' for value in [row['strategy'],amount if diagnostic is not None else 'Not assessed',row['quality_threshold'],labels[state]])+'</tr>'
        text+='</table><p>Mesh agreement and local quality are separate observations. Neither supplies a global error bound. Inspect <a href="stability.json">the mesh controls, differences and thresholds</a>.</p></section>'
    text+="<h2>Demand trajectories</h2><img src='demand_trajectories.png' alt='Consumer stocks in four scenarios'>"
    text+="<h2>Follower payoff surface</h2><img src='rl_payoff_surface.png' alt='RL payoff as a function of delay and announcement'>"
    if plot_settings:
        text+="<h2>Figure controls</h2><p>"+html.escape(plot_settings["interpretation"])+"</p><pre>"+html.escape(json.dumps(plot_settings,indent=2))+"</pre>"
    if audit:text+="<h2>Source formula diagnostics</h2><pre>"+html.escape(json.dumps(audit,indent=2))+"</pre>"
    text+="<p>Parameters and artifact hashes are recorded in manifest.json.</p></html>"
    (Path(directory)/"report.html").write_text(text,encoding="utf-8")
