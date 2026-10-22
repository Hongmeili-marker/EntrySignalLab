"""Indexed PCG64 draws, bounded marginals, copulas and disclosed constraints."""
from hashlib import sha256
from statistics import NormalDist
from math import sqrt,hypot
from fractions import Fraction
from decimal import Decimal,localcontext,MAX_EMAX,MIN_EMIN
from sys import float_info
import numpy as np
from scipy.stats import norm,triang,beta
from scipy.special import erfinv
from .model import finite_number

SAMPLER_VERSION='indexed-pcg64-v2'
INDEX_MAX=2**32-1
def indexed_rng(seed,index,stream,attempt=0):
    for name,value in [('seed',seed),('sample index',index),('draw attempt',attempt)]:
        if isinstance(value,bool) or not isinstance(value,(int,np.integer)) or value<0:raise ValueError(name+' must be a nonnegative integer')
        if name!='seed' and value>INDEX_MAX:raise ValueError(name+' must be <= '+str(INDEX_MAX))
    words=np.frombuffer(sha256(stream.encode('utf-8')).digest(),dtype='<u4').tolist()
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence([int(seed),int(index),int(attempt),*words])))

def wilson_interval(count,total,confidence=.95):
    if isinstance(count,bool) or not isinstance(count,(int,np.integer)) or isinstance(total,bool) or not isinstance(total,(int,np.integer)) or not 0<=count<=total:raise ValueError("interval requires integer 0 <= count <= total")
    count,total=int(count),int(total)
    confidence=finite_number(confidence,"confidence",positive=True)
    if confidence>=1:raise ValueError("confidence must be below one")
    if total==0:return None
    # Near zero, forming 1-confidence loses information before inversion.
    # Keep the established lower-tail path for ordinary/high confidence.
    z=sqrt(2.)*float(erfinv(confidence)) if confidence<.5 else -NormalDist().inv_cdf((1-confidence)/2)
    p=count/total;invn=1/total
    if invn<float_info.min:
        # The endpoints can be representable even when 1/n is not. Keep the
        # integer scale until the final endpoint conversion (120-digit guard).
        with localcontext() as context:
            context.prec=120;context.Emax=MAX_EMAX;context.Emin=MIN_EMIN
            n=Decimal(total);k=Decimal(count);zz=Decimal.from_float(z);z2=zz*zz
            denominator=n+z2
            center=(k+z2/2)/denominator
            half=zz*(k*(n-k)/n+z2/4).sqrt()/denominator
            return [max(0.,float(center-half)),min(1.,float(center+half))]
    z2n=z*z*invn;den=1+z2n
    if count==0:return [0.,z2n/den]
    if count==total:return [1/den,1.]
    center=(p+z2n/2)/den
    half=z*hypot(sqrt(p*(1-p))*sqrt(invn),z*invn/2)/den
    return [max(0.,float(center-half)),min(1.,float(center+half))]

def linear_quantiles(values,probabilities):
    """Linear order statistics with exact endpoint interpolation and one binary64 rounding."""
    ordered=sorted(finite_number(v,'quantile sample') for v in values)
    if not ordered:raise ValueError('quantiles require at least one sample')
    result=[]
    for q in probabilities:
        q=finite_number(q,'quantile probability',minimum=0)
        if q>1:raise ValueError('quantile probability exceeds one')
        h=(len(ordered)-1)*q;i=int(h);f=h-i
        a=ordered[i];b=ordered[min(i+1,len(ordered)-1)]
        weight=Fraction(f)
        value=float(Fraction(a)*(1-weight)+Fraction(b)*weight)
        if not np.isfinite(value) or not a<=value<=b:raise ValueError('quantile interpolation outside finite sample range')
        result.append(value)
    return result

class SamplingPlan:
    def __init__(self,p,ranges,seed=104,marginals=None,correlation=None,constraints=None,constraint_mode='record',max_draw_attempts=100):
        from dataclasses import fields
        names={f.name for f in fields(p)}
        if not isinstance(ranges,dict):raise ValueError('ranges must be an object')
        if marginals is not None and not isinstance(marginals,dict):raise ValueError('marginals must be an object')
        if set(ranges)&set(marginals or {}):raise ValueError('a parameter cannot have both range and marginal definitions')
        specs={name:{'distribution':'uniform','lower':v[0],'upper':v[1]} for name,v in ranges.items() if isinstance(v,list) and len(v)==2}
        if len(specs)!=len(ranges):raise ValueError('each range must contain [lower, upper]')
        specs.update(marginals or {})
        if not specs or set(specs)-names:raise ValueError('sampling requires known parameter names')
        if constraint_mode not in ['record','resample']:raise ValueError('constraint_mode must be record or resample')
        if isinstance(max_draw_attempts,bool) or not isinstance(max_draw_attempts,int) or not 1<=max_draw_attempts<=10000:raise ValueError('max_draw_attempts must be an integer from 1 to 10000')
        indexed_rng(seed,0,'validation');self.seed=int(seed);self.p=p;self.mode=constraint_mode;self.max_attempts=max_draw_attempts;self.specs={};self.domains={}
        for name in sorted(specs):
            s=specs[name]
            if not isinstance(s,dict):raise ValueError('marginal must be an object')
            kind=s.get('distribution','uniform');allowed={'distribution','lower','upper'}|({'mode'} if kind=='triangular' else {'alpha','beta'} if kind=='beta' else set())
            if kind not in ['uniform','triangular','loguniform','beta'] or set(s)-allowed:raise ValueError('unknown marginal distribution or keys')
            lo=finite_number(s.get('lower'),name+' lower',minimum=0);hi=finite_number(s.get('upper'),name+' upper',minimum=0)
            if hi<lo:raise ValueError('marginal upper must be >= lower')
            item={'distribution':kind,'lower':lo,'upper':hi}
            if kind=='loguniform' and lo<=0:raise ValueError('loguniform lower must be positive')
            if kind=='triangular':
                mode=finite_number(s.get('mode'),name+' mode',minimum=0)
                if not lo<=mode<=hi:raise ValueError('triangular mode must be within bounds')
                item['mode']=mode
            if kind=='beta':item.update(alpha=finite_number(s.get('alpha'),'alpha',positive=True),beta=finite_number(s.get('beta'),'beta',positive=True))
            self.specs[name]=item;self.domains[name]=[lo,hi]
        self.correlation=None;self.factor=None;self.correlation_names=[];self.latent_alias={}
        if correlation is not None:
            if not isinstance(correlation,dict) or set(correlation)!= {'names','matrix'}:raise ValueError('correlation requires names and matrix')
            order=correlation['names']
            if not isinstance(order,list) or not order or not all(isinstance(x,str) for x in order) or len(set(order))!=len(order) or set(order)-set(self.specs):raise ValueError('invalid correlation names')
            raw=correlation['matrix']
            if not isinstance(raw,list) or not all(isinstance(row,list) for row in raw):raise ValueError('correlation matrix must be a list of rows')
            matrix=np.asarray([[finite_number(v,'correlation') for v in row] for row in raw],dtype=float)
            if matrix.shape!=(len(order),len(order)) or not np.all(np.isfinite(matrix)) or not np.allclose(matrix,matrix.T,rtol=0,atol=1e-12) or not np.allclose(np.diag(matrix),1,rtol=0,atol=1e-12) or np.any(abs(matrix)>1):raise ValueError('invalid latent correlation matrix')
            self.correlation_names=sorted(order);ix=[order.index(n) for n in self.correlation_names];matrix=matrix[np.ix_(ix,ix)]
            values,vectors=np.linalg.eigh(matrix)
            if min(values)<-1e-12:raise ValueError('correlation matrix must be positive semidefinite')
            try:self.factor=np.linalg.cholesky(matrix);factorization='cholesky'
            except np.linalg.LinAlgError:self.factor=vectors@np.diag(np.sqrt(np.maximum(values,0)));factorization='symmetric_eigen'
            # Exact identical rows with rho=1 describe the same latent variable.
            # Canonicalize its computed value to prevent eigen roundoff from
            # breaking pointwise equality. Other near-singular rows are unchanged.
            for i,name in enumerate(self.correlation_names):
                self.latent_alias[name]=next((self.correlation_names[j] for j in range(i)
                    if matrix[i,j]==1 and np.array_equal(matrix[i],matrix[j])),name)
            self.correlation={'names':self.correlation_names,'matrix':matrix.tolist(),'factorization':factorization,'exact_latent_aliases':self.latent_alias,'interpretation':'Gaussian copula latent-normal correlation; not generally the Pearson correlation of transformed parameters.'}
        if constraints is not None and not isinstance(constraints,list):raise ValueError('constraints must be a list')
        self.constraints=[]
        for c in constraints or []:
            if not isinstance(c,dict) or set(c) not in [{'left','relation','right'},{'left','relation','value'}] or c['left'] not in names or c['relation'] not in ['le','ge']:raise ValueError('invalid constraint')
            if 'right' in c and c['right'] not in names:raise ValueError('unknown constraint right parameter')
            item=dict(c)
            if 'value' in item:item['value']=finite_number(item['value'],'constraint value')
            self.constraints.append(item)
        self.constraints.sort(key=lambda c:repr(sorted(c.items())))
    def proves_equal(self,left,right):
        """Conservative joint-support proof, restricted to exact identical marginals."""
        return (left in self.specs and right in self.specs and self.specs[left]==self.specs[right]
                and left in self.latent_alias and right in self.latent_alias
                and self.latent_alias[left]==self.latent_alias[right])
    def metadata(self):
        return {'sampler_version':SAMPLER_VERSION,'bit_generator':'PCG64','sample_index_domain':[0,INDEX_MAX],'draw_attempt_domain':[0,INDEX_MAX],'parameter_order':list(self.specs),'marginals':self.specs,'correlation':self.correlation,'constraints':self.constraints,'constraint_mode':self.mode,'max_draw_attempts':self.max_attempts,'interpretation':'Index/name keyed paired draws. Rejection sampling, when selected, targets the feasible conditional distribution; raw independent or copula marginals no longer describe the accepted joint distribution.'}
    def constraint_issues(self,full):
        result=[]
        for c in self.constraints:
            a=full[c['left']];b=full[c['right']] if 'right' in c else c['value']
            if (a>b if c['relation']=='le' else a<b):result.append(c)
        return result
    def draw(self,index,attempt=0):
        correlated={}
        if self.factor is not None:
            stream='copula:'+','.join(self.correlation_names);z=self.factor@indexed_rng(self.seed,index,stream,attempt).standard_normal(len(self.correlation_names))
            correlated=dict(zip(self.correlation_names,norm.cdf(z)))
            for name,source in self.latent_alias.items():correlated[name]=correlated[source]
        result={}
        for name,s in self.specs.items():
            lo,hi=s['lower'],s['upper'];u=float(correlated[name]) if name in correlated else float(indexed_rng(self.seed,index,'parameter:'+name,attempt).random())
            u=min(float(np.nextafter(1.,0.)),max(float(np.nextafter(0.,1.)),u));kind=s['distribution']
            if hi==lo:value=lo
            elif kind=='loguniform':value=np.exp((1-u)*np.log(lo)+u*np.log(hi))
            else:
                q=triang.ppf(u,(s['mode']-lo)/(hi-lo)) if kind=='triangular' else beta.ppf(u,s['alpha'],s['beta']) if kind=='beta' else u
                value=(1-q)*lo+q*hi
            if not np.isfinite(value):raise ValueError("marginal inverse transform is outside numerical range")
            result[name]=min(hi,max(lo,float(value)))
        return result
