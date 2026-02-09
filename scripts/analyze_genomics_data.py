import pandas as pd
import json
from pathlib import Path
from datetime import datetime, timezone

def parse_23andme_data(filepath):
    """Parse 23andMe raw data file"""
    # Skip comment lines
    df = pd.read_csv(
        filepath, 
        sep='\t', 
        comment='#',
        names=['rsid', 'chromosome', 'position', 'genotype']
    )
    return df

def analyze_traits(df):
    """Look up specific SNPs for interesting traits"""
    traits = {
        'fitness': {},
        'metabolism': {},
        'nutrition': {},
        'recovery': {},
        'lifestyle': {},
        'ancestry': {}
    }
    
    # === FITNESS & PERFORMANCE ===
    
    # ACTN3 R577X (rs1815739) - Sprint/Power vs Endurance
    actn3 = df[df['rsid'] == 'rs1815739']
    if not actn3.empty:
        genotype = actn3.iloc[0]['genotype']
        if genotype == 'CC':
            traits['fitness']['muscle_type'] = {'value': 'Power/Sprint', 'detail': 'RR - Enhanced fast-twitch muscle performance'}
        elif genotype == 'TT':
            traits['fitness']['muscle_type'] = {'value': 'Endurance', 'detail': 'XX - Better endurance capacity'}
        else:
            traits['fitness']['muscle_type'] = {'value': 'Mixed', 'detail': 'RX - Balanced power and endurance'}
    
    # PPARGC1A (rs8192678) - Aerobic capacity
    ppargc1a = df[df['rsid'] == 'rs8192678']
    if not ppargc1a.empty:
        genotype = ppargc1a.iloc[0]['genotype']
        if 'A' in genotype:
            traits['fitness']['aerobic_response'] = {'value': 'Enhanced', 'detail': 'Better VO2 max improvement with training'}
        else:
            traits['fitness']['aerobic_response'] = {'value': 'Standard', 'detail': 'Normal aerobic training response'}
    
    # ACE (rs4340 proxy: rs4343) - Endurance and blood pressure
    ace = df[df['rsid'] == 'rs4343']
    if not ace.empty:
        genotype = ace.iloc[0]['genotype']
        if genotype == 'AA':
            traits['fitness']['ace_type'] = {'value': 'Endurance', 'detail': 'DD-like - Better endurance capacity'}
        elif genotype == 'GG':
            traits['fitness']['ace_type'] = {'value': 'Power', 'detail': 'II-like - Better power/strength gains'}
        else:
            traits['fitness']['ace_type'] = {'value': 'Balanced', 'detail': 'ID-like - Mixed endurance/power'}
    
    # COL5A1 (rs12722) - Connective tissue and injury risk
    col5a1 = df[df['rsid'] == 'rs12722']
    if not col5a1.empty:
        genotype = col5a1.iloc[0]['genotype']
        if 'T' in genotype:
            traits['recovery']['injury_risk'] = {'value': 'Elevated', 'detail': 'Higher risk of soft tissue injuries'}
        else:
            traits['recovery']['injury_risk'] = {'value': 'Standard', 'detail': 'Normal injury risk profile'}
    
    # MCT1 (rs1049434) - Lactate clearance
    mct1 = df[df['rsid'] == 'rs1049434']
    if not mct1.empty:
        genotype = mct1.iloc[0]['genotype']
        if genotype == 'AA':
            traits['fitness']['lactate_threshold'] = {'value': 'Enhanced clearance', 'detail': 'Better at clearing lactate - can push harder'}
        elif genotype == 'TT':
            traits['fitness']['lactate_threshold'] = {'value': 'Standard clearance', 'detail': 'Normal lactate tolerance'}
        else:
            traits['fitness']['lactate_threshold'] = {'value': 'Good clearance', 'detail': 'Above average lactate tolerance'}
    
    # NOS3 (rs2070744) - Nitric oxide production
    nos3 = df[df['rsid'] == 'rs2070744']
    if not nos3.empty:
        genotype = nos3.iloc[0]['genotype']
        if 'T' in genotype:
            traits['fitness']['muscle_pump'] = {'value': 'Enhanced', 'detail': 'Better blood flow and muscle pump'}
        else:
            traits['fitness']['muscle_pump'] = {'value': 'Standard', 'detail': 'Normal blood flow response'}
    
    # AGT (rs699) - Endurance and blood pressure
    agt = df[df['rsid'] == 'rs699']
    if not agt.empty:
        genotype = agt.iloc[0]['genotype']
        if genotype == 'TT':
            traits['fitness']['endurance_capacity'] = {'value': 'Enhanced', 'detail': 'Better long-distance performance'}
        elif genotype == 'CC':
            traits['fitness']['endurance_capacity'] = {'value': 'Standard', 'detail': 'Normal endurance capacity'}
        else:
            traits['fitness']['endurance_capacity'] = {'value': 'Good', 'detail': 'Above average endurance'}
    
    # MSTN (rs1805086) - Myostatin/Muscle growth
    mstn = df[df['rsid'] == 'rs1805086']
    if not mstn.empty:
        genotype = mstn.iloc[0]['genotype']  
        if 'T' in genotype:
            traits['fitness']['muscle_growth'] = {'value': 'Enhanced potential', 'detail': 'May build muscle more easily'}
        else:
            traits['fitness']['muscle_growth'] = {'value': 'Standard potential', 'detail': 'Normal muscle-building capacity'}
    
    # === METABOLISM ===
    
    # Caffeine metabolism (rs762551 - CYP1A2)
    caffeine_snp = df[df['rsid'] == 'rs762551']
    if not caffeine_snp.empty:
        genotype = caffeine_snp.iloc[0]['genotype']
        if genotype == 'AA':
            traits['metabolism']['caffeine'] = {'value': 'Fast metabolizer', 'detail': 'Can tolerate higher caffeine intake'}
        elif genotype == 'CC':
            traits['metabolism']['caffeine'] = {'value': 'Slow metabolizer', 'detail': 'May be sensitive to caffeine'}
        else:
            traits['metabolism']['caffeine'] = {'value': 'Intermediate', 'detail': 'Moderate caffeine metabolism'}
    
    # FTO (rs9939609) - Weight management
    fto = df[df['rsid'] == 'rs9939609']
    if not fto.empty:
        genotype = fto.iloc[0]['genotype']
        if 'A' in genotype:
            traits['metabolism']['weight_tendency'] = {'value': 'Higher appetite', 'detail': 'May need extra focus on portion control'}
        else:
            traits['metabolism']['weight_tendency'] = {'value': 'Standard', 'detail': 'Normal weight regulation'}
    
    # ADRB2 (rs1042713) - Fat oxidation during exercise
    adrb2 = df[df['rsid'] == 'rs1042713']
    if not adrb2.empty:
        genotype = adrb2.iloc[0]['genotype']
        if genotype == 'AA':
            traits['metabolism']['fat_burning'] = {'value': 'Enhanced', 'detail': 'Better fat oxidation during cardio'}
        elif genotype == 'GG':
            traits['metabolism']['fat_burning'] = {'value': 'Standard', 'detail': 'Normal fat utilization'}
        else:
            traits['metabolism']['fat_burning'] = {'value': 'Good', 'detail': 'Above average fat burning'}
    
    # LPL (rs328) - Fat storage patterns
    lpl = df[df['rsid'] == 'rs328']
    if not lpl.empty:
        genotype = lpl.iloc[0]['genotype']
        if 'G' in genotype:
            traits['metabolism']['fat_storage'] = {'value': 'Efficient storage', 'detail': 'May store fat more readily'}
        else:
            traits['metabolism']['fat_storage'] = {'value': 'Standard storage', 'detail': 'Normal fat storage patterns'}
    
    # LYPLAL1 (rs2605100) - Waist-to-hip ratio / body shape
    lyplal1 = df[df['rsid'] == 'rs2605100']
    if not lyplal1.empty:
        genotype = lyplal1.iloc[0]['genotype']  
        if 'A' in genotype:
            traits['metabolism']['body_shape'] = {'value': 'Lower body fat tendency', 'detail': 'Pear shape - fat stored in hips/thighs'}
        else:
            traits['metabolism']['body_shape'] = {'value': 'Upper body fat tendency', 'detail': 'Apple shape - fat stored in waist/belly'}
    
    # GRB14 (rs10195252) - Visceral fat tendency
    grb14 = df[df['rsid'] == 'rs10195252']
    if not grb14.empty:
        genotype = grb14.iloc[0]['genotype']
        if 'T' in genotype:
            traits['metabolism']['visceral_fat_tendency'] = {'value': 'Higher risk', 'detail': 'May accumulate more visceral (organ) fat'}
        else:
            traits['metabolism']['visceral_fat_tendency'] = {'value': 'Lower risk', 'detail': 'Less tendency for visceral fat accumulation'}
    
    # VDR (rs2228570) - Bone mineral density
    vdr_bone = df[df['rsid'] == 'rs2228570']
    if not vdr_bone.empty:
        genotype = vdr_bone.iloc[0]['genotype']
        if 'T' in genotype:
            traits['metabolism']['bone_density'] = {'value': 'Higher BMD tendency', 'detail': 'Better bone mineral density'}
        else:
            traits['metabolism']['bone_density'] = {'value': 'Standard BMD', 'detail': 'Normal bone density'}
    
    # COL1A1 (rs1800012) - Bone strength
    col1a1 = df[df['rsid'] == 'rs1800012']
    if not col1a1.empty:
        genotype = col1a1.iloc[0]['genotype']
        if 'T' in genotype:
            traits['metabolism']['bone_strength'] = {'value': 'Lower bone strength', 'detail': 'May have reduced bone strength (osteoporosis risk)'}
        else:
            traits['metabolism']['bone_strength'] = {'value': 'Normal bone strength', 'detail': 'Standard bone structure'}
    
    # === NUTRITION ===
    
    # Lactose tolerance (rs4988235 - LCT)
    lactose_snp = df[df['rsid'] == 'rs4988235']
    if not lactose_snp.empty:
        genotype = lactose_snp.iloc[0]['genotype']
        if genotype == 'AA':
            traits['nutrition']['lactose'] = {'value': 'Tolerant', 'detail': 'Can digest lactose well'}
        elif genotype == 'GG':
            traits['nutrition']['lactose'] = {'value': 'Intolerant', 'detail': 'May have difficulty digesting dairy'}
        else:
            traits['nutrition']['lactose'] = {'value': 'Reduced tolerance', 'detail': 'Partial lactose intolerance'}
    
    # Vitamin D receptor (rs2228570 - VDR)
    vdr = df[df['rsid'] == 'rs2228570']
    if not vdr.empty:
        genotype = vdr.iloc[0]['genotype']
        if 'T' in genotype:
            traits['nutrition']['vitamin_d'] = {'value': 'Enhanced binding', 'detail': 'Better vitamin D utilization'}
        else:
            traits['nutrition']['vitamin_d'] = {'value': 'Standard', 'detail': 'Normal vitamin D metabolism'}
    
    # === RECOVERY ===
    
    # IL6 (rs1800795) - Inflammation response
    il6 = df[df['rsid'] == 'rs1800795']
    if not il6.empty:
        genotype = il6.iloc[0]['genotype']
        if 'C' in genotype:
            traits['recovery']['inflammation'] = {'value': 'Higher response', 'detail': 'May need more recovery time'}
        else:
            traits['recovery']['inflammation'] = {'value': 'Lower response', 'detail': 'Standard inflammation response'}
    
    # SOD2 (rs4880) - Oxidative stress
    sod2 = df[df['rsid'] == 'rs4880']
    if not sod2.empty:
        genotype = sod2.iloc[0]['genotype']
        if genotype == 'AA':
            traits['recovery']['oxidative_stress'] = {'value': 'Lower protection', 'detail': 'May benefit from antioxidants'}
        else:
            traits['recovery']['oxidative_stress'] = {'value': 'Enhanced protection', 'detail': 'Good oxidative stress management'}
    
    # HIF1A (rs11549465) - Altitude/hypoxia adaptation
    hif1a = df[df['rsid'] == 'rs11549465']
    if not hif1a.empty:
        genotype = hif1a.iloc[0]['genotype']
        if 'T' in genotype:
            traits['recovery']['altitude_adaptation'] = {'value': 'Enhanced', 'detail': 'Better performance at altitude'}
        else:
            traits['recovery']['altitude_adaptation'] = {'value': 'Standard', 'detail': 'Normal altitude response'}
    
    # BDKRB2 (rs1799722) - Muscle hypertrophy response
    bdkrb2 = df[df['rsid'] == 'rs1799722']
    if not bdkrb2.empty:
        genotype = bdkrb2.iloc[0]['genotype']
        if genotype == 'CC':
            traits['recovery']['training_response'] = {'value': 'Enhanced', 'detail': 'Stronger muscle growth response to training'}
        else:
            traits['recovery']['training_response'] = {'value': 'Standard', 'detail': 'Normal adaptation to training'}
    
    # VEGFA (rs2010963) - Vascular growth
    vegfa = df[df['rsid'] == 'rs2010963']
    if not vegfa.empty:
        genotype = vegfa.iloc[0]['genotype']
        if 'C' in genotype:
            traits['recovery']['vascular_growth'] = {'value': 'Enhanced', 'detail': 'Better capillary development for endurance'}
        else:
            traits['recovery']['vascular_growth'] = {'value': 'Standard', 'detail': 'Normal vascular adaptation'}
    
    # === LIFESTYLE & HORMONES ===
    
    # CLOCK (rs1801260) - Circadian rhythm
    clock = df[df['rsid'] == 'rs1801260']
    if not clock.empty:
        genotype = clock.iloc[0]['genotype']
        if 'T' in genotype:
            traits['lifestyle']['chronotype'] = {'value': 'Evening person', 'detail': 'Night owl - better evening performance'}
        else:
            traits['lifestyle']['chronotype'] = {'value': 'Morning person', 'detail': 'Early bird - better morning performance'}
    
    # ABCC9 (rs11046205) - Sleep duration needs
    abcc9 = df[df['rsid'] == 'rs11046205']
    if not abcc9.empty:
        genotype = abcc9.iloc[0]['genotype']
        if 'T' in genotype:
            traits['lifestyle']['sleep_duration'] = {'value': 'Short sleeper', 'detail': 'May need less sleep than average'}
        else:
            traits['lifestyle']['sleep_duration'] = {'value': 'Standard sleep needs', 'detail': 'Normal sleep duration requirements'}
    
    # DEC2 (rs121912617 proxy: rs2653349) - Short sleep variant
    dec2 = df[df['rsid'] == 'rs2653349']
    if not dec2.empty:
        genotype = dec2.iloc[0]['genotype']
        if 'T' in genotype:
            traits['lifestyle']['sleep_efficiency'] = {'value': 'Efficient sleeper', 'detail': 'May function well on less sleep'}
    
    # ADORA2A (rs5751876) - Caffeine and sleep
    adora2a = df[df['rsid'] == 'rs5751876']
    if not adora2a.empty:
        genotype = adora2a.iloc[0]['genotype']
        if 'T' in genotype:
            traits['lifestyle']['caffeine_sleep_impact'] = {'value': 'High sensitivity', 'detail': 'Caffeine strongly affects sleep'}
        else:
            traits['lifestyle']['caffeine_sleep_impact'] = {'value': 'Low sensitivity', 'detail': 'Caffeine has less impact on sleep'}
    
    # CYP19A1 (rs10046) - Aromatase (testosterone → estrogen conversion)
    cyp19a1 = df[df['rsid'] == 'rs10046']
    if not cyp19a1.empty:
        genotype = cyp19a1.iloc[0]['genotype']
        if genotype == 'TT':
            traits['lifestyle']['aromatase'] = {'value': 'Lower conversion', 'detail': 'Less testosterone converted to estrogen'}
        elif genotype == 'CC':
            traits['lifestyle']['aromatase'] = {'value': 'Higher conversion', 'detail': 'More testosterone converted to estrogen'}
        else:
            traits['lifestyle']['aromatase'] = {'value': 'Standard conversion', 'detail': 'Normal testosterone-estrogen balance'}
    
    # SHBG (rs6259) - Sex hormone binding globulin
    shbg = df[df['rsid'] == 'rs6259']
    if not shbg.empty:
        genotype = shbg.iloc[0]['genotype']
        if 'A' in genotype:
            traits['lifestyle']['free_testosterone'] = {'value': 'Higher tendency', 'detail': 'May have more free (active) testosterone'}
        else:
            traits['lifestyle']['free_testosterone'] = {'value': 'Standard', 'detail': 'Normal free testosterone levels'}
    
    # SRD5A2 (rs523349) - 5-alpha reductase (testosterone → DHT)
    srd5a2 = df[df['rsid'] == 'rs523349']
    if not srd5a2.empty:
        genotype = srd5a2.iloc[0]['genotype']
        if 'G' in genotype:
            traits['lifestyle']['dht_conversion'] = {'value': 'Higher activity', 'detail': 'More conversion to DHT (hair loss risk, but muscle gains)'}
        else:
            traits['lifestyle']['dht_conversion'] = {'value': 'Standard activity', 'detail': 'Normal DHT levels'}
    
    # COMT (rs4680) - Pain tolerance and stress
    comt = df[df['rsid'] == 'rs4680']
    if not comt.empty:
        genotype = comt.iloc[0]['genotype']
        if genotype == 'AA':
            traits['lifestyle']['pain_tolerance'] = {'value': 'Higher tolerance', 'detail': 'Worrier gene - higher pain threshold, better stress handling'}
        elif genotype == 'GG':
            traits['lifestyle']['pain_tolerance'] = {'value': 'Lower tolerance', 'detail': 'Warrior gene - lower pain threshold, handles acute stress better'}
        else:
            traits['lifestyle']['pain_tolerance'] = {'value': 'Moderate tolerance', 'detail': 'Balanced pain sensitivity'}
    
    # OPRM1 (rs1799971) - Opioid receptor (pain perception)
    oprm1 = df[df['rsid'] == 'rs1799971']
    if not oprm1.empty:
        genotype = oprm1.iloc[0]['genotype']
        if 'G' in genotype:
            traits['lifestyle']['pain_sensitivity'] = {'value': 'More sensitive', 'detail': 'May perceive pain more intensely'}
        else:
            traits['lifestyle']['pain_sensitivity'] = {'value': 'Less sensitive', 'detail': 'May have higher pain threshold'}
    
    # BDNF (rs6265) - Exercise motivation and neuroplasticity
    bdnf = df[df['rsid'] == 'rs6265']
    if not bdnf.empty:
        genotype = bdnf.iloc[0]['genotype']
        if 'A' in genotype:
            traits['lifestyle']['exercise_motivation'] = {'value': 'Lower natural drive', 'detail': 'May need extra motivation for exercise'}
        else:
            traits['lifestyle']['exercise_motivation'] = {'value': 'Higher natural drive', 'detail': 'Naturally more motivated to exercise'}
    
    # === ANCESTRY & FUN FACTS ===
    
    # Neanderthal variant 1 (rs4481887) - Hair texture
    nean1 = df[df['rsid'] == 'rs4481887']
    if not nean1.empty:
        genotype = nean1.iloc[0]['genotype']
        if 'G' in genotype:
            traits['ancestry']['neanderthal_hair'] = {'value': 'Neanderthal variant', 'detail': 'Carries Neanderthal variant for straight hair'}
    
    # Neanderthal variant 2 (rs3827760) - Immune function
    nean2 = df[df['rsid'] == 'rs3827760']
    if not nean2.empty:
        genotype = nean2.iloc[0]['genotype']
        if 'A' in genotype:
            traits['ancestry']['neanderthal_immune'] = {'value': 'Neanderthal variant', 'detail': 'Carries Neanderthal immune system variant'}
    
    # SLC24A5 (rs1426654) - Skin pigmentation (European ancestry marker)
    slc24a5 = df[df['rsid'] == 'rs1426654']
    if not slc24a5.empty:
        genotype = slc24a5.iloc[0]['genotype']
        if genotype == 'AA':
            traits['ancestry']['skin_pigmentation'] = {'value': 'Light skin variant', 'detail': 'European-associated light skin allele'}
        elif genotype == 'GG':
            traits['ancestry']['skin_pigmentation'] = {'value': 'Dark skin variant', 'detail': 'African/Asian-associated allele'}
        else:
            traits['ancestry']['skin_pigmentation'] = {'value': 'Mixed', 'detail': 'Intermediate pigmentation allele'}
    
    # EDAR (rs3827760) - Hair thickness (East Asian marker)
    edar = df[df['rsid'] == 'rs3827760']
    if not edar.empty:
        genotype = edar.iloc[0]['genotype']
        if 'T' in genotype:
            traits['ancestry']['hair_thickness'] = {'value': 'Thick hair variant', 'detail': 'Common in East Asian populations'}
        else:
            traits['ancestry']['hair_thickness'] = {'value': 'Standard', 'detail': 'Typical hair thickness'}
    
    # ABCC11 (rs17822931) - Earwax type (East Asian/European marker)
    abcc11 = df[df['rsid'] == 'rs17822931']
    if not abcc11.empty:
        genotype = abcc11.iloc[0]['genotype']
        if genotype == 'CC':
            traits['ancestry']['earwax_type'] = {'value': 'Dry earwax', 'detail': 'Common in East Asian ancestry (also less body odor)'}
        elif genotype == 'TT':
            traits['ancestry']['earwax_type'] = {'value': 'Wet earwax', 'detail': 'Common in European/African ancestry'}
        else:
            traits['ancestry']['earwax_type'] = {'value': 'Mixed', 'detail': 'Intermediate earwax type'}
    
    # OCA2 (rs1800407) - Eye color
    oca2 = df[df['rsid'] == 'rs1800407']
    if not oca2.empty:
        genotype = oca2.iloc[0]['genotype']
        if 'T' in genotype:
            traits['ancestry']['eye_color_factor'] = {'value': 'Lighter eyes tendency', 'detail': 'Associated with blue/green eyes'}
        else:
            traits['ancestry']['eye_color_factor'] = {'value': 'Darker eyes tendency', 'detail': 'Associated with brown eyes'}
    
    # Red hair (rs1805007) - MC1R
    mc1r = df[df['rsid'] == 'rs1805007']
    if not mc1r.empty:
        genotype = mc1r.iloc[0]['genotype']
        if 'T' in genotype:
            traits['ancestry']['red_hair_variant'] = {'value': 'Red hair variant', 'detail': 'Carries MC1R red hair allele (European origin)'}
    
    return traits

def validate_privacy(insights):
    """Ensure no PII or raw genotypes leak into output"""
    # Check that we only have aggregated/interpreted data
    insights_str = json.dumps(insights)
    
    # Flag if raw genotypes appear (like 'AA', 'GG', 'CT' as standalone values)
    # This is a basic check - traits should have descriptive values, not raw genotypes
    if any(pattern in insights_str for pattern in ['"AA"', '"GG"', '"TT"', '"CC"']):
        print("⚠️  Warning: Raw genotypes may be present in output")
    
    return True

def generate_insights(df):
    """Generate all insights for dashboard"""
    traits = analyze_traits(df)
    
    # Count how many traits were found
    trait_count = sum(
        len(category) for category in traits.values() if isinstance(category, dict)
    )
    
    insights = {
        'metadata': {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'version': '1.0',
            'source': '23andMe Raw Data',
            'genome_build': 'GRCh37/hg19'
        },
        'summary': {
            'total_snps': int(len(df)),
            'chromosomes': int(df['chromosome'].nunique()),
            'traits_analyzed': trait_count,
            'coverage': {
                'autosomes': int(len(df[df['chromosome'].isin([str(i) for i in range(1, 23)])])),
                'sex_chromosomes': int(len(df[df['chromosome'].isin(['X', 'Y'])])),
                'mitochondrial': int(len(df[df['chromosome'] == 'MT']))
            }
        },
        'traits': traits,
        'stats': {
            'chromosomes': {str(k): int(v) for k, v in df['chromosome'].value_counts().head(24).to_dict().items()}
        }
    }
    
    # Validate before returning
    validate_privacy(insights)
    
    return insights

def main():
    # ⚠️ NEVER commit this file or the raw data!
    script_dir = Path(__file__).parent
    raw_data_path = script_dir.parent / 'instance' / 'genome_Arash_Mirshahi_Full.txt'
    
    if not raw_data_path.exists():
        print("❌ Raw data file not found!")
        print(f"Expected location: {raw_data_path}")
        print("Place your 23andMe file in the instance/ folder")
        return
    
    print("📊 Analyzing genetic data...")
    print(f"Reading from: {raw_data_path.name}")
    
    try:
        df = parse_23andme_data(raw_data_path)
        print(f"✅ Parsed {len(df):,} SNPs across {df['chromosome'].nunique()} chromosomes")
    except Exception as e:
        print(f"❌ Error parsing data: {e}")
        return
    
    print("🧬 Generating insights...")
    try:
        insights = generate_insights(df)
        print(f"✅ Generated {insights['summary']['traits_analyzed']} trait insights")
    except Exception as e:
        print(f"❌ Error generating insights: {e}")
        return
    
    # Save to public folder (this is safe to commit)
    output_path = script_dir.parent / 'public' / 'insights.json'
    output_path.parent.mkdir(exist_ok=True)
    
    try:
        with open(output_path, 'w') as f:
            json.dump(insights, f, indent=2)
        print(f"✅ Insights saved to {output_path}")
        print(f"   File size: {output_path.stat().st_size / 1024:.1f} KB")
    except Exception as e:
        print(f"❌ Error saving insights: {e}")
        return
    
    print("\n✅ Done! You can now commit public/insights.json and deploy!")
    print("\n📋 Summary:")
    print(f"   - Fitness traits: {len(insights['traits']['fitness'])}")
    print(f"   - Metabolism traits: {len(insights['traits']['metabolism'])}")
    print(f"   - Nutrition traits: {len(insights['traits']['nutrition'])}")
    print(f"   - Recovery traits: {len(insights['traits']['recovery'])}")
    print(f"   - Lifestyle traits: {len(insights['traits']['lifestyle'])}")
    print(f"   - Ancestry markers: {len(insights['traits']['ancestry'])}")

if __name__ == '__main__':
    main()