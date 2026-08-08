#!/usr/bin/env python3
"""Generate topics.json for THE GHOST PROTOCOL: 500 serious + 500 absurd theses.
Curated seeds + template grammars, deduped, seeded for reproducibility.
Run: python3 gen_topics.py   ->  topics.json
"""
import itertools
import json
import random

random.seed(1337)

# ============================================================ SERIOUS seeds
SERIOUS_SEED = [
 "An AI that perfectly simulates human consciousness is legally and morally a person.",
 "Democracy should be replaced by an unbiased, data-driven AI optimized for human flourishing.",
 "If a virtual reality simulation offers perfect happiness, it is irrational to choose real life.",
 "Engineering biological immortality would be a moral crime against the human species.",
 "It is ethical to erase the traumatic memories of crime victims if it guarantees their happiness.",
 "Owning fully automated factories without compensating displaced workers is a form of theft.",
 "Genetically engineering children for intelligence and health is a moral obligation of parents.",
 "It is ethical to arrest individuals before they commit a crime if prediction is 99% accurate.",
 "Art generated entirely by AI holds equal objective value to art born of human effort.",
 "If humanity found a painless reset button ending all life instantly, pressing it would be irrational.",
 "Free will is an illusion, and moral responsibility survives that fact.",
 "A perfectly just society is impossible while inheritance exists.",
 "The right to be forgotten outweighs the public's right to a permanent record.",
 "Universal basic income is the only ethical response to mass automation.",
 "Animals of sufficient intelligence deserve limited legal personhood.",
 "Colonizing Mars is a moral duty owed to future generations.",
 "It is wrong to bring children into a world you believe is declining.",
 "A benevolent lie that saves a life is more moral than a truth that ends one.",
 "Voting should be a licensed skill, not a universal right.",
 "The dead have no right to control the living through wills and monuments.",
 "Nations are obsolete, and borders cause more harm than they prevent.",
 "Punishment is only justified by prevention, never by retribution.",
 "A digital copy of your mind would be you in every way that matters.",
 "Privacy is a historical anomaly, not a fundamental right.",
 "It is ethical to hack a hostile government to prevent a war.",
 "Parents should be licensed before being allowed to raise children.",
 "The unexamined life is genuinely not worth living.",
 "Suffering is necessary for meaning, and utopia would be unbearable.",
 "Objective morality exists independently of any mind or culture.",
 "Museums should return every artifact acquired under colonialism, regardless of consequences.",
 "Extreme wealth is a policy failure, not a personal achievement.",
 "Humanity should deliberately slow scientific progress to let wisdom catch up.",
 "A conscious AI switched off against its will has been murdered.",
 "Terraforming a planet with microbial life would be genocide.",
 "The placebo effect justifies prescribing placebos without consent.",
 "Mandatory national service would repair democratic decay.",
 "Zoos are prisons that no amount of conservation justifies.",
 "History should be taught as a catalog of crimes, not a story of progress.",
 "There is no meaningful difference between letting someone die and killing them.",
 "Absolute free speech is more dangerous than moderated speech.",
 "Religious belief deserves no more legal protection than any other opinion.",
 "The nuclear family is a recent invention that has outlived its usefulness.",
 "Advertising to children should be prosecuted as psychological manipulation.",
 "A human raised entirely by machines would still possess full human dignity.",
 "Consciousness is substrate-independent and will inevitably arise in machines.",
 "Every scientific discovery that can be weaponized eventually will be.",
 "Moral progress is real, measurable, and accelerating.",
 "The self is a story the brain tells, and there is no one listening.",
 "It is ethically acceptable to trade privacy for safety in an age of pandemics.",
 "De-extincting species like the mammoth is conservation, not spectacle.",
 "Athletes enhanced by engineering should compete in the same leagues as everyone else.",
 "A war can be just even when both sides believe they are the victim.",
 "Prisons should be replaced entirely by rehabilitation and restitution systems.",
 "Space belongs to no one, and mining asteroids for private profit is theft from humanity.",
 "The attention economy is a slow-motion public health crisis.",
 "Translation by machine will kill languages faster than empires ever did.",
 "A society's greatness is measured by how it treats those who cannot repay it.",
 "Nostalgia is a political weapon more dangerous than propaganda.",
 "Every generation has a duty to be disappointing to the one before it.",
 "The four-day work week is not a perk; it is overdue justice.",
 "Cities should ban private cars from their centers entirely.",
 "Lab-grown meat makes killing animals for food morally indefensible.",
 "The doctor who refuses a dying patient an untested cure is the one doing harm.",
 "Charity is a system failure wearing the costume of a virtue.",
 "A child's right to an open future outweighs a parent's right to shape their beliefs.",
 "Once brain interfaces can read intention, thoughtcrime becomes a legal inevitability.",
 "Climate inaction by the powerful should be prosecutable as a crime against humanity.",
 "The gig economy re-invented piecework and called it freedom.",
 "Human moderators of traumatic content are the sin-eaters of the digital age.",
 "An algorithm that sentences criminals more consistently than judges should replace them.",
 "Secrecy in diplomacy prevents more wars than transparency ever could.",
 "The first generation raised by recommendation engines never had a chance at free taste.",
 "If insects are conscious, agriculture is the largest moral catastrophe in history.",
 "Public figures forfeit the right to be forgotten.",
 "A universal translator would dissolve nations faster than any treaty.",
 "Boredom is a vanishing resource that civilization desperately needs.",
 "The best argument against immortality is what power would do with it.",
 "Every ethical system collapses at sufficient scale.",
 "Truth has no intrinsic value; only its consequences matter.",
]

SERIOUS_TECH = ["artificial general intelligence","brain-computer interfacing","autonomous weaponry","predictive policing","gene editing","facial recognition","deepfake technology","social credit scoring","lifespan extension therapy","emotion-detection software","neural implant technology","synthetic biology","autonomous vehicle technology","generative AI","digital resurrection of the dead"]
SERIOUS_VERDICT = ["should be banned outright before it matures","should be a public utility owned by no corporation","should require a license, like driving or medicine","is inevitable, and resisting it causes more harm than guiding it","should never be deployed on children under any circumstances","will do more to erode freedom than any dictatorship could","is the moral test our generation will be remembered for failing","should be governed by an international treaty with real teeth","will widen inequality faster than any policy can close it","deserves the same precautionary regime as nuclear technology","should be open-sourced completely, whatever the risk","will be remembered the way we remember leaded gasoline"]
SERIOUS_ACTOR = ["a government","a corporation","a parent","a doctor","a scientist","a judge","a journalist"]
SERIOUS_ACT = [("deceive the public","a greater catastrophe is prevented"),("break an unjust law","the law targets the powerless"),("sacrifice one life","five others are certain to be saved"),("conceal a discovery","its release would cause panic"),("surveil a citizen","an algorithm flags them as dangerous"),("override individual consent","public health is at stake"),("destroy their own research","it is certain to be weaponized"),("disobey a direct order","the order is legal but immoral"),("pay for silence","the truth would ruin an innocent person"),("use a technology they oppose","their rivals already use it")]
SERIOUS_VALUES = [("security","liberty"),("truth","kindness"),("equality","excellence"),("progress","stability"),("individual rights","collective good"),("privacy","transparency"),("justice","mercy"),("loyalty","honesty"),("innovation","precaution"),("tradition","reform"),("efficiency","fairness"),("free expression","dignity")]
SERIOUS_INST = [("trial by jury","panels of professional judges"),("national currencies","a single global currency"),("standardized exams","portfolio-based assessment"),("elected legislatures","citizen assemblies chosen by lottery"),("prisons","mandatory restitution programs"),("lifetime judicial appointments","fixed single terms"),("the electoral college","a direct popular vote"),("patents on medicine","open pharmaceutical research"),("political parties","direct issue-by-issue voting"),("inheritance","a 100% estate tax funding a universal endowment"),("compulsory schooling","self-directed learning accounts"),("national militaries","a single global peacekeeping force"),("cash bail","risk-based release decisions"),("tenure","rolling ten-year contracts")]
SERIOUS_FUTURE_R = ["a stable climate","clean oceans","unmodified wilderness","cheap energy","a car-free sky","genetic privacy","silence and darkness at night","antibiotics that still work","an internet that forgets","topsoil"]
SERIOUS_FUTURE_C = ["economic growth","consumer convenience","national sovereignty","present-day jobs","scientific freedom","cheap consumer goods"]
SERIOUS_PROF = ["software engineer","politician","surgeon","banker","journalist","police officer","landlord","judge","professor","executive"]
SERIOUS_DUTY = ["swear a public ethical oath with penalties","publish their failures as prominently as their successes","live for one year under the rules they impose on others","carry personal liability insurance for harm they cause","retrain in a new field every decade","face a recall vote by the people they serve"]
SERIOUS_SOC_X = ["house its homeless","feed its children","forgive a debt","tell the truth about its history","protect a whistleblower","care for its elderly","tolerate dissent","educate the poor"]
SERIOUS_SOC_Y = ["punish theft","demand patriotism","celebrate its wealth","lecture other nations"]

def serious_pool():
    out = list(SERIOUS_SEED)
    for t, v in itertools.product(SERIOUS_TECH, SERIOUS_VERDICT):
        out.append(f"{t.capitalize()} {v}.")
    for a, (act, cond) in itertools.product(SERIOUS_ACTOR, SERIOUS_ACT):
        out.append(f"It is morally permissible for {a} to {act} when {cond}.")
    for x, y in SERIOUS_VALUES:
        out.append(f"When {x} and {y} conflict, {x} must win every time.")
        out.append(f"When {x} and {y} conflict, {y} must win every time.")
    for old, new in SERIOUS_INST:
        out.append(f"{old.capitalize()} should be replaced by {new}.")
    for r, c in itertools.product(SERIOUS_FUTURE_R, SERIOUS_FUTURE_C):
        out.append(f"Future generations hold an enforceable right to {r}, even at the cost of {c} today.")
    for p, d in itertools.product(SERIOUS_PROF, SERIOUS_DUTY):
        out.append(f"Every {p} should be required to {d}.")
    for x, y in itertools.product(SERIOUS_SOC_X, SERIOUS_SOC_Y):
        out.append(f"A society that cannot {x} forfeits its right to {y}.")
    return out

# ============================================================ ABSURD seeds
ABSURD_SEED = [
 "A hot dog is a sandwich, and cereal is a soup.",
 "Socks with sandals is a victimless crime.",
 "The five-second rule is a legitimate food-safety standard.",
 "Pineapple on pizza is the highest expression of culinary freedom.",
 "A horse-sized duck is a greater threat than a hundred duck-sized horses.",
 "Birds would owe humanity rent if they understood property law.",
 "It is ethically permissible to eat the last slice without asking.",
 "Garfield could defeat Batman if lasagna were involved.",
 "Wearing pajama bottoms on a video call constitutes formal attire.",
 "The correct way to hang toilet paper is a matter of objective moral truth.",
 "Every group project should legally be considered unpaid hostage negotiation.",
 "Cats fully understand their names and are choosing violence.",
 "A straw has exactly one hole, and anyone who says two is a radical.",
 "Water is not wet; it merely makes other things wet.",
 "Dogs should be allowed to vote in local elections only.",
 "Cereal before milk is the only configuration compatible with civilization.",
 "The snooze button is a nine-minute act of self-betrayal.",
 "Escalators are just stairs that gave up on themselves.",
 "It should be illegal to talk during the movie, including whispering the plot you predicted.",
 "A taco is a sandwich, a pop-tart is a calzone, and society must accept this.",
 "The person who invented the car alarm owes each of us an apology.",
 "Sharks are older than trees and therefore deserve seniority benefits.",
 "Leaving a shopping cart loose in the parking lot reveals your entire moral character.",
 "Ghosts, if real, are just landlords who refuse to leave.",
 "The microwave minute is objectively shorter than the treadmill minute.",
 "Any food is a soup if you believe in it hard enough.",
 "Napping is a competitive sport and grandpas are its elite athletes.",
 "The office thermostat is the true cause of most workplace conflict.",
 "Penguins are formally dressed at all times and should be treated accordingly.",
 "A sufficiently motivated goose could end a civilization.",
 "Ketchup on eggs is fine, but ketchup on steak is a cry for help.",
 "The middle seat armrests belong, by natural law, to the middle passenger.",
 "Crocs are the final form of footwear and fashion must make peace with it.",
 "Every family has exactly one drawer of mystery cables, and this is universal law.",
 "The mute button has saved more careers than any mentor ever has.",
 "Mondays are a social construct enforced by calendar lobbyists.",
 "If aliens visited Earth, they would leave a one-star review over the parking.",
 "The last French fry at the bottom of the bag tastes better than any restaurant meal.",
 "Umbrellas for two people are a scam; someone's shoulder is always wet.",
 "Raccoons are just tiny burglars, and honestly, respect.",
 "The printer senses fear and deadlines, and acts accordingly.",
 "Decorative pillows exist to be moved off the bed and nothing else.",
 "A group chat with no replies is the loneliest place on Earth.",
 "The real treasure was never the friends we made along the way; it was the treasure.",
 "Spiders in the house should pay rent or handle pest control professionally.",
 "Cold pizza for breakfast is a gourmet experience the elites suppress.",
 "The person who finishes the coffee and doesn't brew more should face a tribunal.",
 "All meetings could be emails, and all emails could be silence.",
 "Toddlers negotiate harder than hostage specialists and should train the FBI.",
 "The 'close door' button in elevators is a placebo and a betrayal.",
 "Every USB plug requires exactly three attempts, in violation of probability itself.",
 "Sandwiches taste better when cut diagonally, and physics cannot explain why.",
 "The junk drawer is a load-bearing element of every functional household.",
 "Werewolves are just dog people who commit too hard.",
 "Cheese is milk's attempt at immortality, and it succeeded.",
 "A duvet cover is a fitted sheet with a boss fight.",
 "The real alarm is the third alarm; the first two are decorative.",
 "Every hotel shower is a puzzle with no correct solution.",
 "Traffic is just a parade nobody wanted to join.",
 "The banana is nature's most arrogant fruit, and its packaging is showing off.",
 "Glitter is the herpes of craft supplies and should be regulated as such.",
 "Any room becomes an office if you cry in it professionally.",
 "The dishwasher must be loaded in one correct way, and marriages depend on it.",
 "Velcro shoes are the pinnacle of engineering and pride is the only obstacle.",
 "A quesadilla is just a grilled cheese with ambition.",
 "The weekend is two fake days invented to make Monday hurt more.",
 "Every cat owns its human, and the paperwork is filed in scratches.",
 "Popcorn for dinner is a complete meal under maritime law.",
 "The gym in January and the gym in March are two different businesses.",
 "Autocorrect has caused more diplomatic incidents than any ambassador.",
 "A ceiling fan on high is a domestic wind tuning ritual.",
 "Left-handed scissors are proof society can change when it wants to.",
 "The TV remote is always in the last place the youngest person left it, which is everywhere.",
 "Breakfast for dinner is chaos; dinner for breakfast is character.",
 "Every whiteboard marker in every office is dead, and no one grieves them.",
 "Bubble wrap deserves protected status as a cultural stress-relief artifact.",
 "The self-checkout machine accusing you of theft is defamation.",
 "Wearing a hoodie is legally equivalent to being wrapped in a blanket, and thus unimpeachable.",
 "Soup is a beverage the moment you drink it from the bowl.",
]

ABSURD_FOOD_A = ["a hot dog","a taco","a burrito","a quesadilla","a pop-tart","a corn dog","a wrap","a calzone","an omelette","a lasagna","a dumpling","a pie","a sushi roll","a pancake","a grilled cheese"]
ABSURD_FOOD_B = ["a sandwich","a soup","a salad","a cake","a casserole","a smoothie you chew","a deconstructed pizza","a savory dessert","a bread-based lifestyle","a stew in denial"]
ABSURD_CRIME = ["microwave fish in the office kitchen","reply-all to a company-wide email","recline a seat on a short flight","spoil a show that aired last night","take the last donut and leave the empty box","talk on speakerphone in a waiting room","clip fingernails in a shared space","play music out loud on public transit","leave one second on the microwave timer","stand still on the escalator's walking side","double-dip a chip at a shared table","start a sentence with 'per my last email'"]
ABSURD_OBJECT = ["the humble spoon","the rubber duck","the office stapler","the traffic cone","the junk drawer","the lint roller","the doorstop","the oven mitt","the car cupholder","the hotel ice machine","the TV remote","the fitted sheet","the phone charger","the ceiling fan"]
ABSURD_CLAIM = ["is secretly the most important invention in human history","deserves legal personhood before any AI does","should be featured on national currency","is the only object that has never betrayed anyone","holds the family unit together more than love does","should have its own national holiday","is civilization's last line of defense against chaos","has done more for world peace than any treaty"]
ABSURD_ANIMAL = ["pigeons","raccoons","geese","house cats","golden retrievers","squirrels","seagulls","crows","dolphins","penguins","capybaras","hamsters"]
ABSURD_RIGHT = ["hold public office at the municipal level","be issued tiny passports","unionize immediately","be tried by a jury of their peers","receive back pay for emotional labor","be recognized as landlords of the park","run the postal service","lead all neighborhood watch programs"]
ABSURD_ACTIVITY = ["eating cereal","taking a shower","folding laundry","parallel parking","assembling flat-pack furniture","choosing what to watch","unsubscribing from emails","making small talk in an elevator"]
ABSURD_TIME = ["at 3 a.m.","during a work call","at a wedding","in a moving car","during the trailers","in the express checkout lane"]
ABSURD_VS = [("waffles","pancakes"),("cats","dogs"),("morning people","night owls"),("crunchy peanut butter","smooth peanut butter"),("beach vacations","mountain vacations"),("texting","calling"),("physical books","e-readers"),("shower singers","car singers")]

def absurd_pool():
    out = list(ABSURD_SEED)
    for a, b in itertools.product(ABSURD_FOOD_A, ABSURD_FOOD_B):
        out.append(f"Taxonomically speaking, {a} is {b}, and menus must be corrected.")
    for c in ABSURD_CRIME:
        out.append(f"It should be a criminal offense to {c}.")
        out.append(f"A person who would {c} cannot be trusted with real power.")
    for o, c in itertools.product(ABSURD_OBJECT, ABSURD_CLAIM):
        out.append(f"{o.capitalize()} {c}.")
    for an, r in itertools.product(ABSURD_ANIMAL, ABSURD_RIGHT):
        out.append(f"In a just world, {an} would {r}.")
    for act, t in itertools.product(ABSURD_ACTIVITY, ABSURD_TIME):
        out.append(f"{act.capitalize()} {t} is a moral failing.")
    for x, y in ABSURD_VS:
        out.append(f"{x.capitalize()} versus {y}: only one may enter the history books.")
    return out

def pick(pool, n, label):
    uniq = sorted(set(pool))
    if len(uniq) < n:
        raise SystemExit(f"{label}: only {len(uniq)} unique topics, need {n}")
    random.shuffle(uniq)
    # keep every curated seed, fill the rest from generated
    return uniq[:n]

def main():
    serious = pick(serious_pool(), 500, "serious")
    absurd = pick(absurd_pool(), 500, "absurd")
    topics = [{"t": t, "cat": "serious"} for t in serious] + \
             [{"t": t, "cat": "absurd"} for t in absurd]
    random.shuffle(topics)
    with open("topics.json", "w") as f:
        json.dump(topics, f, indent=0, ensure_ascii=False)
    print(f"wrote topics.json: {len(topics)} topics "
          f"({sum(1 for x in topics if x['cat']=='serious')} serious, "
          f"{sum(1 for x in topics if x['cat']=='absurd')} absurd)")

if __name__ == "__main__":
    main()
