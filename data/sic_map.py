"""data/sic_map.py - SEC SIC code -> Yahoo sector/industry mapping (H-03).

SEC EDGAR discloses each registrant's **SIC** (Standard Industrial
Classification) code and description in its submissions JSON. SIC is the most
authoritative first-hand US regulatory classification, but it is *not* the Yahoo
taxonomy the rest of this engine consumes (``map_sector_industry``,
``node_from_yahoo``, peer buckets, WACC sanity bands). This module bridges the
two.

Resolution order (first hit wins):
  1. Exact 4-digit SIC code   — curated, highest precision.
  2. 3-digit SIC group        — e.g. 367x electronics.
  3. 2-digit SIC major group  — broad division fallback.
  4. ``sicDescription`` keyword match — last resort when the code is unknown.

Every returned ``industry`` string is a **Yahoo canonical industry** so that the
downstream hard rule (``classification.classifier.map_sector_industry``) and the
taxonomy mapper (``classification.taxonomy.node_from_yahoo``) fire correctly.

This is pure data + pure functions: no network, no side effects, fully offline.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Exact SIC code -> (Yahoo sector, Yahoo industry)
# ---------------------------------------------------------------------------
SIC_TO_YAHOO: Dict[str, Tuple[str, str]] = {
    # ---- Technology / Semiconductors & hardware ----
    "3571": ("Technology", "Computer Hardware"),            # Electronic Computers
    "3572": ("Technology", "Computer Hardware"),            # Computer Storage Devices
    "3575": ("Technology", "Computer Hardware"),            # Computer Terminals
    "3576": ("Technology", "Computer Hardware"),            # Computer Communications Equip
    "3577": ("Technology", "Computer Hardware"),            # Computer Peripheral Equip
    "3578": ("Technology", "Computer Hardware"),            # Calculating & Accounting Machines
    "3579": ("Technology", "Computer Hardware"),            # Office Machines NEC
    "3674": ("Technology", "Semiconductors"),               # Semiconductors & Related Devices
    "3672": ("Technology", "Electronic Components"),        # Printed Circuit Boards
    "3670": ("Technology", "Electronic Components"),        # Electronic Components NEC
    "3671": ("Technology", "Electronic Components"),        # Electron Tubes
    "3675": ("Technology", "Electronic Components"),        # Electronic Connectors
    "3676": ("Technology", "Electronic Components"),        # Electronic Resistors
    "3677": ("Technology", "Electronic Components"),        # Electronic Coils & Transformers
    "3678": ("Technology", "Electronic Components"),        # Electronic Connectors (alt)
    "3679": ("Technology", "Electronic Components"),        # Electronic Components NEC
    "3661": ("Technology", "Communication Equipment"),      # Telephone & Telegraph Apparatus
    "3663": ("Technology", "Communication Equipment"),      # Radio & TV Comm Equipment
    "3669": ("Technology", "Communication Equipment"),      # Communications Equipment NEC
    "3826": ("Technology", "Scientific & Technical Instruments"),  # Laboratory Analytical Instruments
    "3827": ("Technology", "Scientific & Technical Instruments"),  # Optical Instruments & Lenses
    "3823": ("Technology", "Scientific & Technical Instruments"),  # Industrial Instruments
    "7372": ("Technology", "Software - Application"),       # Services-Prepackaged Software
    "7371": ("Technology", "Software - Infrastructure"),    # Services-Computer Programming
    "7373": ("Technology", "Software - Infrastructure"),    # Services-Computer Integrated Sys
    "7374": ("Technology", "Information Technology Services"),  # Services-Computer Processing
    "7375": ("Communication Services", "Interactive Media"),    # Services-Information Retrieval
    "7376": ("Technology", "Information Technology Services"),  # Services-Computer Facilities Mgmt
    "7377": ("Technology", "Information Technology Services"),  # Services-Computer Rental & Leasing
    "7378": ("Technology", "Information Technology Services"),  # Services-Computer Maintenance
    "7379": ("Technology", "Information Technology Services"),  # Services-Computer Related NEC
    "7370": ("Technology", "Information Technology Services"),  # Services-Computer Programming/Data
    "7389": ("Industrials", "Specialty Business Services"),  # Services-Business Services NEC
    "3568": ("Industrials", "Specialty Industrial Machinery"),  # General Industrial Machinery NEC

    # ---- Financial Services / Banks / Insurance ----
    "6021": ("Financial Services", "Banks - Diversified"),  # National Commercial Banks
    "6022": ("Financial Services", "Banks - Regional"),     # State Commercial Banks
    "6029": ("Financial Services", "Banks - Regional"),     # Commercial Banks NEC
    "6035": ("Financial Services", "Banks - Savings"),      # Savings Institutions, Federal
    "6036": ("Financial Services", "Banks - Savings"),      # Savings Institutions, Not Federal
    "6099": ("Financial Services", "Banks - Regional"),     # Functions Related to Depository Banking
    "6111": ("Financial Services", "Credit Services"),      # Federal & Federally Sponsored Credit
    "6141": ("Financial Services", "Credit Services"),      # Personal Credit Institutions
    "6153": ("Financial Services", "Credit Services"),      # Short-Term Business Credit
    "6159": ("Financial Services", "Credit Services"),      # Miscellaneous Business Credit
    "6199": ("Financial Services", "Credit Services"),      # Finance Services NEC
    "6211": ("Financial Services", "Capital Markets"),      # Security Brokers & Dealers
    "6221": ("Financial Services", "Capital Markets"),      # Commodity Contracts Brokers
    "6282": ("Financial Services", "Capital Markets"),      # Investment Advice
    "6289": ("Financial Services", "Capital Markets"),      # Security & Commodity Services NEC
    "6311": ("Financial Services", "Insurance - Life"),     # Life Insurance
    "6321": ("Financial Services", "Insurance - Life"),     # Accident & Health Insurance
    "6324": ("Healthcare", "Healthcare Plans"),             # Hospital & Medical Service Plans
    "6331": ("Financial Services", "Insurance - Property & Casualty"),  # Fire, Marine & Casualty
    "6351": ("Financial Services", "Insurance - Specialty"),  # Surety Insurance
    "6361": ("Financial Services", "Insurance - Specialty"),  # Title Insurance
    "6399": ("Financial Services", "Insurance - Specialty"),  # Insurance Carriers NEC
    "6411": ("Financial Services", "Insurance Brokers"),    # Insurance Agents, Brokers & Service
    "6156": ("Financial Services", "Credit Services"),      # Federal & Federally Sponsored Credit (alt)
    "6770": ("Financial Services", "Capital Markets"),      # Blank Checks (SPACs)
    "6792": ("Financial Services", "Capital Markets"),      # Oil Royalty Traders
    "6798": ("Real Estate", "REIT - Diversified"),          # Real Estate Investment Trusts
    "6799": ("Financial Services", "Capital Markets"),      # Investors NEC
    "6726": ("Financial Services", "Asset Management"),     # Investment Offices NEC

    # ---- Healthcare ----
    "2833": ("Healthcare", "Drug Manufacturers - Specialty & Generic"),  # Medicinal Chemicals
    "2834": ("Healthcare", "Drug Manufacturers - General"),  # Pharmaceutical Preparations
    "2835": ("Healthcare", "Diagnostics & Research"),       # In Vitro & In Vivo Diagnostics
    "2836": ("Healthcare", "Biotechnology"),                # Biological Products (no diagnostic)
    "2830": ("Healthcare", "Drug Manufacturers - General"),  # Drugs
    "3841": ("Healthcare", "Medical Devices"),              # Surgical & Medical Instruments
    "3842": ("Healthcare", "Medical Devices"),              # Orthopedic, Prosthetic & Surgical
    "3843": ("Healthcare", "Medical Devices"),              # Dental Equipment & Supplies
    "3844": ("Healthcare", "Medical Devices"),              # X-Ray Apparatus & Tubes
    "3845": ("Healthcare", "Medical Devices"),              # Electromedical Apparatus
    "3851": ("Healthcare", "Medical Instruments & Supplies"),  # Ophthalmic Goods
    "5047": ("Healthcare", "Medical Distribution"),         # Medical, Dental & Hospital Equip
    "5122": ("Healthcare", "Medical Distribution"),         # Drugs, Proprietary & Druggists Sundries
    "8011": ("Healthcare", "Medical Care Facilities"),      # Offices & Clinics of Doctors
    "8062": ("Healthcare", "Medical Care Facilities"),      # General Medical & Surgical Hospitals
    "8051": ("Healthcare", "Medical Care Facilities"),      # Skilled Nursing Care Facilities
    "8731": ("Healthcare", "Diagnostics & Research"),       # Commercial Physical & Biological Research
    "8734": ("Healthcare", "Diagnostics & Research"),       # Testing Laboratories

    # ---- Energy ----
    "1311": ("Energy", "Oil & Gas E&P"),                    # Crude Petroleum & Natural Gas
    "1321": ("Energy", "Oil & Gas E&P"),                    # Natural Gas Liquids
    "1382": ("Energy", "Oil & Gas Equipment & Services"),   # Oil & Gas Field Services
    "1389": ("Energy", "Oil & Gas Equipment & Services"),   # Oil & Gas Field Services NEC
    "2911": ("Energy", "Oil & Gas Refining & Marketing"),   # Petroleum Refining
    "4610": ("Energy", "Oil & Gas Midstream"),              # Pipe Lines (No Natural Gas)
    "4922": ("Energy", "Oil & Gas Midstream"),              # Natural Gas Transmission
    "4923": ("Energy", "Oil & Gas Midstream"),              # Natural Gas Transmission & Distribution
    "4924": ("Utilities", "Utilities - Regulated Gas"),     # Natural Gas Distribution
    "1094": ("Energy", "Uranium"),                          # Uranium-Radium-Vanadium Ores

    # ---- Utilities ----
    "4911": ("Utilities", "Utilities - Regulated Electric"),  # Electric Services
    "4931": ("Utilities", "Utilities - Diversified"),       # Electric & Other Services Combined
    "4932": ("Utilities", "Utilities - Regulated Gas"),     # Gas & Other Services Combined
    "4939": ("Utilities", "Utilities - Diversified"),       # Combination Utilities NEC
    "4941": ("Utilities", "Utilities - Regulated Water"),   # Water Supply
    "4991": ("Utilities", "Utilities - Independent Power Producers"),  # Cogeneration Services

    # ---- Materials / Commodity ----
    "1040": ("Basic Materials", "Gold"),                    # Gold Mining
    "1021": ("Basic Materials", "Copper"),                  # Copper Ores
    "1020": ("Basic Materials", "Copper"),                  # Copper Ores (alt)
    "1000": ("Basic Materials", "Other Industrial Metals & Mining"),  # Metal Mining
    "1090": ("Basic Materials", "Other Industrial Metals & Mining"),  # Miscellaneous Metal Ores
    "3312": ("Basic Materials", "Steel"),                   # Steel Works, Blast Furnaces
    "3316": ("Basic Materials", "Steel"),                   # Steel Works (alt)
    "3334": ("Basic Materials", "Aluminum"),                # Primary Smelting & Refining of Aluminum
    "3330": ("Basic Materials", "Other Industrial Metals & Mining"),  # Primary Smelting (Nonferrous)
    "2810": ("Basic Materials", "Chemicals"),               # Industrial Inorganic Chemicals
    "2819": ("Basic Materials", "Specialty Chemicals"),     # Industrial Inorganic Chemicals NEC
    "2820": ("Basic Materials", "Specialty Chemicals"),     # Plastic Materials & Synthetic Resins
    "2821": ("Basic Materials", "Specialty Chemicals"),     # Plastic Materials
    "2851": ("Basic Materials", "Specialty Chemicals"),     # Paints, Varnishes & Lacquers
    "2860": ("Basic Materials", "Specialty Chemicals"),     # Industrial Organic Chemicals
    "2870": ("Basic Materials", "Agricultural Inputs"),     # Agricultural Chemicals
    "2890": ("Basic Materials", "Specialty Chemicals"),     # Miscellaneous Chemical Products
    "2879": ("Basic Materials", "Agricultural Inputs"),     # Pesticides & Agricultural Chemicals
    "3241": ("Basic Materials", "Building Materials"),      # Cement, Hydraulic
    "3270": ("Basic Materials", "Building Materials"),      # Concrete, Gypsum & Plaster Products
    "2650": ("Consumer Cyclical", "Packaging & Containers"),  # Paperboard Containers & Boxes
    "2631": ("Basic Materials", "Paper & Paperboard"),      # Paperboard Mills
    "2621": ("Basic Materials", "Paper & Paperboard"),      # Paper Mills
    "3950": ("Consumer Cyclical", "Packaging & Containers"),  # Pens, Pencils & Other Office Supplies
    "3350": ("Basic Materials", "Other Industrial Metals & Mining"),  # Rolling & Drawing Nonferrous

    # ---- Industrials ----
    "3721": ("Industrials", "Aerospace & Defense"),         # Aircraft
    "3724": ("Industrials", "Aerospace & Defense"),         # Aircraft Engines & Engine Parts
    "3728": ("Industrials", "Aerospace & Defense"),         # Aircraft Parts & Auxiliary Equipment
    "3760": ("Industrials", "Aerospace & Defense"),         # Guided Missiles & Space Vehicles
    "3812": ("Industrials", "Aerospace & Defense"),         # Search, Detection, Navigation Systems
    "3560": ("Industrials", "Specialty Industrial Machinery"),  # General Industrial Machinery
    "3561": ("Industrials", "Specialty Industrial Machinery"),  # Pumps & Pumping Equipment
    "3562": ("Industrials", "Specialty Industrial Machinery"),  # Ball & Roller Bearings
    "3569": ("Industrials", "Specialty Industrial Machinery"),  # General Industrial Machinery NEC
    "3530": ("Industrials", "Farm & Heavy Construction Machinery"),  # Construction Machinery
    "3523": ("Industrials", "Farm & Heavy Construction Machinery"),  # Farm Machinery & Equipment
    "3531": ("Industrials", "Farm & Heavy Construction Machinery"),  # Construction Machinery (alt)
    "4011": ("Industrials", "Railroads"),                  # Railroads, Line-Haul Operating
    "4213": ("Industrials", "Trucking"),                   # Trucking (No Local)
    "4210": ("Industrials", "Trucking"),                   # Trucking & Courier Services
    "4512": ("Industrials", "Airlines"),                   # Air Transportation, Scheduled
    "4513": ("Industrials", "Airlines"),                   # Air Courier Services
    "4412": ("Industrials", "Marine Shipping"),            # Deep Sea Foreign Transportation
    "4491": ("Energy", "Oil & Gas Midstream"),             # Marine Cargo Handling
    "4953": ("Industrials", "Waste Management"),           # Refuse Systems
    "4950": ("Industrials", "Waste Management"),           # Sanitary Services
    "1623": ("Industrials", "Engineering & Construction"),  # Water, Sewer & Pipeline Construction
    "1700": ("Industrials", "Engineering & Construction"),  # Construction - Special Trade Contractors
    "1731": ("Industrials", "Engineering & Construction"),  # Electrical Work
    "1520": ("Consumer Cyclical", "Residential Construction"),  # General Building Contractors-Residential
    "1540": ("Industrials", "Engineering & Construction"),  # General Building Contractors-Nonresidential
    "7380": ("Industrials", "Specialty Business Services"),  # Miscellaneous Business Services
    "7361": ("Industrials", "Staffing & Employment Services"),  # Employment Agencies
    "7363": ("Industrials", "Staffing & Employment Services"),  # Help Supply Services
    "8742": ("Industrials", "Consulting Services"),        # Services-Management Consulting
    "8711": ("Industrials", "Engineering & Construction"),  # Services-Engineering Services

    # ---- Consumer Cyclical ----
    "3711": ("Consumer Cyclical", "Auto Manufacturers"),   # Motor Vehicles & Car Bodies
    "3714": ("Consumer Cyclical", "Auto Parts"),           # Motor Vehicle Parts & Accessories
    "3716": ("Consumer Cyclical", "Auto Manufacturers"),   # Motor Homes
    "5500": ("Consumer Cyclical", "Auto Dealers"),         # Motor Vehicle Dealers (New & Used)
    "5310": ("Consumer Cyclical", "Department Stores"),    # Retail-Department Stores
    "5311": ("Consumer Cyclical", "Department Stores"),    # Retail-Department Stores (alt)
    "5651": ("Consumer Cyclical", "Apparel Retail"),       # Retail-Family Clothing Stores
    "5621": ("Consumer Cyclical", "Apparel Retail"),       # Retail-Womens Clothing Stores
    "5661": ("Consumer Cyclical", "Apparel Retail"),       # Retail-Shoe Stores
    "5961": ("Consumer Cyclical", "Internet Retail"),      # Retail-Catalog & Mail-Order Houses
    "5945": ("Consumer Cyclical", "Specialty Retail"),     # Retail-Hobby, Toy & Game Shops
    "5531": ("Consumer Cyclical", "Specialty Retail"),     # Retail-Auto & Home Supply Stores
    "5731": ("Consumer Cyclical", "Specialty Retail"),     # Retail-Radio, TV & Consumer Electronics
    "5812": ("Consumer Cyclical", "Restaurants"),          # Retail-Eating Places
    "5813": ("Consumer Cyclical", "Restaurants"),          # Retail-Drinking Places
    "7011": ("Consumer Cyclical", "Lodging"),              # Hotels & Motels
    "7990": ("Consumer Cyclical", "Leisure"),              # Services-Miscellaneous Amusement
    "7841": ("Consumer Cyclical", "Entertainment"),        # Services-Video Tape Rental
    "2320": ("Consumer Cyclical", "Apparel Manufacturing"),  # Mens & Boys Furnishings
    "2330": ("Consumer Cyclical", "Apparel Manufacturing"),  # Womens & Misses Outerwear
    "3140": ("Consumer Cyclical", "Footwear & Accessories"),  # Footwear (No Rubber)
    "2510": ("Consumer Cyclical", "Furnishings, Fixtures & Appliances"),  # Household Furniture
    "3630": ("Consumer Cyclical", "Furnishings, Fixtures & Appliances"),  # Household Appliances

    # ---- Consumer Staples ----
    "2000": ("Consumer Defensive", "Packaged Foods"),      # Food & Kindred Products
    "2011": ("Consumer Defensive", "Packaged Foods"),      # Meat Packing Plants
    "2020": ("Consumer Defensive", "Packaged Foods"),      # Dairy Products
    "2050": ("Consumer Defensive", "Packaged Foods"),      # Bakery Products
    "2064": ("Consumer Defensive", "Confectioners"),       # Candy & Other Confectionery
    "2086": ("Consumer Defensive", "Beverages - Non-Alcoholic"),  # Bottled & Canned Soft Drinks
    "2080": ("Consumer Defensive", "Beverages - Non-Alcoholic"),  # Beverages
    "2082": ("Consumer Defensive", "Beverages - Brewers"),  # Malt Beverages
    "2084": ("Consumer Defensive", "Beverages - Wineries & Distilleries"),  # Wines, Brandy & Brandy Spirits
    "2085": ("Consumer Defensive", "Beverages - Wineries & Distilleries"),  # Distilled & Blended Liquors
    "2111": ("Consumer Defensive", "Tobacco"),             # Cigarettes
    "2141": ("Consumer Defensive", "Tobacco"),             # Tobacco Stemming & Redrying
    "5411": ("Consumer Defensive", "Grocery Stores"),      # Retail-Grocery Stores
    "5412": ("Consumer Defensive", "Grocery Stores"),      # Retail-Convenience Stores
    "5331": ("Consumer Defensive", "Discount Stores"),     # Retail-Variety Stores
    "2840": ("Consumer Defensive", "Household & Personal Products"),  # Soap & Other Detergents
    "2844": ("Consumer Defensive", "Household & Personal Products"),  # Perfumes, Cosmetics & Toiletries
    "0100": ("Consumer Defensive", "Farm Products"),       # Agricultural Production-Crops
    "0200": ("Consumer Defensive", "Farm Products"),       # Agricultural Production-Livestock

    # ---- Communication Services ----
    "4812": ("Communication Services", "Telecom Services"),  # Radiotelephone Communications
    "4813": ("Communication Services", "Telecom Services"),  # Telephone Communications
    "4814": ("Communication Services", "Telecom Services"),  # Telephone Communications (alt)
    "4832": ("Communication Services", "Broadcasting"),    # Radio Broadcasting Stations
    "4833": ("Communication Services", "Broadcasting"),    # Television Broadcasting Stations
    "4841": ("Communication Services", "Entertainment"),   # Cable & Other Pay Television Services
    "2711": ("Communication Services", "Publishing"),      # Newspapers: Publishing
    "2721": ("Communication Services", "Publishing"),      # Periodicals: Publishing
    "2731": ("Communication Services", "Publishing"),      # Books: Publishing
    "2741": ("Communication Services", "Publishing"),      # Miscellaneous Publishing
    "7812": ("Communication Services", "Entertainment"),   # Services-Motion Picture Production
    "7822": ("Communication Services", "Entertainment"),   # Services-Motion Picture Distribution
    "7311": ("Communication Services", "Advertising Agencies"),  # Services-Advertising Agencies
    "7310": ("Communication Services", "Advertising Agencies"),  # Services-Advertising
    "7997": ("Communication Services", "Gambling"),        # Membership Sports & Recreation Clubs

    # ---- Conglomerate ----
    "6710": ("Financial Services", "Conglomerates"),       # Offices of Bank Holding Companies
    "6719": ("Industrials", "Conglomerates"),              # Offices of Holding Companies NEC
    "9995": ("Industrials", "Conglomerates"),              # Nonoperating Establishments
}

# ---------------------------------------------------------------------------
# 2-digit SIC major group -> (Yahoo sector, Yahoo industry) — broad fallback
# ---------------------------------------------------------------------------
SIC2_TO_YAHOO: Dict[str, Tuple[str, str]] = {
    "01": ("Consumer Defensive", "Farm Products"),
    "02": ("Consumer Defensive", "Farm Products"),
    "07": ("Consumer Defensive", "Agricultural Inputs"),
    "10": ("Basic Materials", "Other Industrial Metals & Mining"),
    "12": ("Energy", "Coal"),
    "13": ("Energy", "Oil & Gas E&P"),
    "14": ("Basic Materials", "Other Industrial Metals & Mining"),
    "15": ("Industrials", "Engineering & Construction"),
    "16": ("Industrials", "Engineering & Construction"),
    "17": ("Industrials", "Engineering & Construction"),
    "20": ("Consumer Defensive", "Packaged Foods"),
    "21": ("Consumer Defensive", "Tobacco"),
    "22": ("Consumer Cyclical", "Textile Manufacturing"),
    "23": ("Consumer Cyclical", "Apparel Manufacturing"),
    "24": ("Basic Materials", "Lumber & Wood Production"),
    "25": ("Consumer Cyclical", "Furnishings, Fixtures & Appliances"),
    "26": ("Basic Materials", "Paper & Paperboard"),
    "27": ("Communication Services", "Publishing"),
    "28": ("Healthcare", "Drug Manufacturers - General"),
    "29": ("Energy", "Oil & Gas Refining & Marketing"),
    "30": ("Consumer Cyclical", "Rubber & Plastics"),
    "31": ("Consumer Cyclical", "Footwear & Accessories"),
    "32": ("Basic Materials", "Building Materials"),
    "33": ("Basic Materials", "Steel"),
    "34": ("Industrials", "Metal Fabrication"),
    "35": ("Industrials", "Specialty Industrial Machinery"),
    "36": ("Technology", "Electronic Components"),
    "37": ("Consumer Cyclical", "Auto Manufacturers"),
    "38": ("Technology", "Scientific & Technical Instruments"),
    "39": ("Consumer Cyclical", "Leisure"),
    "40": ("Industrials", "Railroads"),
    "41": ("Industrials", "Trucking"),
    "42": ("Industrials", "Trucking"),
    "44": ("Industrials", "Marine Shipping"),
    "45": ("Industrials", "Airlines"),
    "47": ("Industrials", "Integrated Freight & Logistics"),
    "48": ("Communication Services", "Telecom Services"),
    "49": ("Utilities", "Utilities - Regulated Electric"),
    "50": ("Industrials", "Industrial Distribution"),
    "51": ("Healthcare", "Medical Distribution"),
    "52": ("Consumer Cyclical", "Home Improvement Retail"),
    "53": ("Consumer Defensive", "Discount Stores"),
    "54": ("Consumer Defensive", "Grocery Stores"),
    "55": ("Consumer Cyclical", "Auto Dealers"),
    "56": ("Consumer Cyclical", "Apparel Retail"),
    "57": ("Consumer Cyclical", "Specialty Retail"),
    "58": ("Consumer Cyclical", "Restaurants"),
    "59": ("Consumer Cyclical", "Specialty Retail"),
    "60": ("Financial Services", "Banks - Regional"),
    "61": ("Financial Services", "Credit Services"),
    "62": ("Financial Services", "Capital Markets"),
    "63": ("Financial Services", "Insurance - Diversified"),
    "64": ("Financial Services", "Insurance Brokers"),
    "65": ("Real Estate", "Real Estate - Services"),
    "67": ("Financial Services", "Asset Management"),
    "70": ("Consumer Cyclical", "Lodging"),
    "72": ("Consumer Cyclical", "Personal Services"),
    "73": ("Technology", "Information Technology Services"),
    "75": ("Industrials", "Rental & Leasing Services"),
    "76": ("Industrials", "Specialty Business Services"),
    "78": ("Communication Services", "Entertainment"),
    "79": ("Consumer Cyclical", "Leisure"),
    "80": ("Healthcare", "Medical Care Facilities"),
    "81": ("Industrials", "Consulting Services"),
    "82": ("Consumer Defensive", "Education & Training Services"),
    "83": ("Consumer Cyclical", "Personal Services"),
    "87": ("Industrials", "Consulting Services"),
    "89": ("Industrials", "Consulting Services"),
}

# ---------------------------------------------------------------------------
# sicDescription keyword -> (Yahoo sector, Yahoo industry) — last resort
# Order matters: first substring hit wins, so put specific before generic.
# ---------------------------------------------------------------------------
SIC_DESC_KEYWORDS: Tuple[Tuple[str, str, str], ...] = (
    ("semiconductor", "Technology", "Semiconductors"),
    ("printed circuit", "Technology", "Electronic Components"),
    ("electronic component", "Technology", "Electronic Components"),
    ("prepackaged software", "Technology", "Software - Application"),
    ("software", "Technology", "Software - Application"),
    ("computer programming", "Technology", "Software - Infrastructure"),
    ("computer processing", "Technology", "Information Technology Services"),
    ("computer integrated", "Technology", "Information Technology Services"),
    ("computer communications", "Technology", "Computer Hardware"),
    ("computer peripheral", "Technology", "Computer Hardware"),
    ("electronic computer", "Technology", "Computer Hardware"),
    ("computer storage", "Technology", "Computer Hardware"),
    ("telephone & telegraph", "Technology", "Communication Equipment"),
    ("communications equipment", "Technology", "Communication Equipment"),
    ("radio & tv comm", "Technology", "Communication Equipment"),
    ("laboratory analytical", "Technology", "Scientific & Technical Instruments"),
    ("optical instruments", "Technology", "Scientific & Technical Instruments"),
    ("measuring & controlling", "Technology", "Scientific & Technical Instruments"),
    ("national commercial bank", "Financial Services", "Banks - Diversified"),
    ("state commercial bank", "Financial Services", "Banks - Regional"),
    ("commercial bank", "Financial Services", "Banks - Regional"),
    ("savings institution", "Financial Services", "Banks - Savings"),
    ("personal credit", "Financial Services", "Credit Services"),
    ("short-term business credit", "Financial Services", "Credit Services"),
    ("business credit", "Financial Services", "Credit Services"),
    ("finance services", "Financial Services", "Credit Services"),
    ("security brokers", "Financial Services", "Capital Markets"),
    ("investment advice", "Financial Services", "Capital Markets"),
    ("commodity contracts", "Financial Services", "Capital Markets"),
    ("investors nec", "Financial Services", "Capital Markets"),
    ("blank checks", "Financial Services", "Capital Markets"),
    ("real estate investment trust", "Real Estate", "REIT - Diversified"),
    ("life insurance", "Financial Services", "Insurance - Life"),
    ("accident & health", "Financial Services", "Insurance - Life"),
    ("fire, marine", "Financial Services", "Insurance - Property & Casualty"),
    ("fire, marine & casualty", "Financial Services", "Insurance - Property & Casualty"),
    ("surety insurance", "Financial Services", "Insurance - Specialty"),
    ("title insurance", "Financial Services", "Insurance - Specialty"),
    ("insurance agents", "Financial Services", "Insurance Brokers"),
    ("insurance carriers", "Financial Services", "Insurance - Specialty"),
    ("hospital & medical service plan", "Healthcare", "Healthcare Plans"),
    ("pharmaceutical preparation", "Healthcare", "Drug Manufacturers - General"),
    ("medicinal chemical", "Healthcare", "Drug Manufacturers - Specialty & Generic"),
    ("biological product", "Healthcare", "Biotechnology"),
    ("in vitro & in vivo", "Healthcare", "Diagnostics & Research"),
    ("commercial physical", "Healthcare", "Diagnostics & Research"),
    ("testing laborator", "Healthcare", "Diagnostics & Research"),
    ("surgical & medical instrument", "Healthcare", "Medical Devices"),
    ("orthopedic", "Healthcare", "Medical Devices"),
    ("dental equipment", "Healthcare", "Medical Devices"),
    ("electromedical", "Healthcare", "Medical Devices"),
    ("x-ray apparatus", "Healthcare", "Medical Devices"),
    ("ophthalmic goods", "Healthcare", "Medical Instruments & Supplies"),
    ("medical, dental & hospital", "Healthcare", "Medical Distribution"),
    ("drugs, proprietar", "Healthcare", "Medical Distribution"),
    ("general medical & surgical hospital", "Healthcare", "Medical Care Facilities"),
    ("offices & clinics", "Healthcare", "Medical Care Facilities"),
    ("crude petroleum", "Energy", "Oil & Gas E&P"),
    ("natural gas liquids", "Energy", "Oil & Gas E&P"),
    ("oil & gas field", "Energy", "Oil & Gas Equipment & Services"),
    ("petroleum refining", "Energy", "Oil & Gas Refining & Marketing"),
    ("pipe lines", "Energy", "Oil & Gas Midstream"),
    ("natural gas transmission", "Energy", "Oil & Gas Midstream"),
    ("natural gas distribution", "Utilities", "Utilities - Regulated Gas"),
    ("uranium", "Energy", "Uranium"),
    ("electric services", "Utilities", "Utilities - Regulated Electric"),
    ("electric & other services", "Utilities", "Utilities - Diversified"),
    ("gas & other services", "Utilities", "Utilities - Regulated Gas"),
    ("water supply", "Utilities", "Utilities - Regulated Water"),
    ("cogeneration", "Utilities", "Utilities - Independent Power Producers"),
    ("gold mining", "Basic Materials", "Gold"),
    ("copper ores", "Basic Materials", "Copper"),
    ("steel works", "Basic Materials", "Steel"),
    ("aluminum", "Basic Materials", "Aluminum"),
    ("industrial inorganic chem", "Basic Materials", "Specialty Chemicals"),
    ("plastic materials", "Basic Materials", "Specialty Chemicals"),
    ("paints, varnishes", "Basic Materials", "Specialty Chemicals"),
    ("industrial organic chem", "Basic Materials", "Specialty Chemicals"),
    ("agricultural chem", "Basic Materials", "Agricultural Inputs"),
    ("pesticides", "Basic Materials", "Agricultural Inputs"),
    ("cement", "Basic Materials", "Building Materials"),
    ("paperboard container", "Consumer Cyclical", "Packaging & Containers"),
    ("paperboard mill", "Basic Materials", "Paper & Paperboard"),
    ("paper mill", "Basic Materials", "Paper & Paperboard"),
    ("aircraft", "Industrials", "Aerospace & Defense"),
    ("guided missile", "Industrials", "Aerospace & Defense"),
    ("search, detection, navigation", "Industrials", "Aerospace & Defense"),
    ("general industrial machinery", "Industrials", "Specialty Industrial Machinery"),
    ("construction machinery", "Industrials", "Farm & Heavy Construction Machinery"),
    ("farm machinery", "Industrials", "Farm & Heavy Construction Machinery"),
    ("railroad", "Industrials", "Railroads"),
    ("trucking", "Industrials", "Trucking"),
    ("air transportation", "Industrials", "Airlines"),
    ("air courier", "Industrials", "Airlines"),
    ("deep sea foreign", "Industrials", "Marine Shipping"),
    ("refuse system", "Industrials", "Waste Management"),
    ("sanitary service", "Industrials", "Waste Management"),
    ("construction - special trade", "Industrials", "Engineering & Construction"),
    ("general building contractors", "Industrials", "Engineering & Construction"),
    ("services-engineering", "Industrials", "Engineering & Construction"),
    ("management consulting", "Industrials", "Consulting Services"),
    ("management services", "Industrials", "Consulting Services"),
    ("employment agenc", "Industrials", "Staffing & Employment Services"),
    ("help supply", "Industrials", "Staffing & Employment Services"),
    ("business services", "Industrials", "Specialty Business Services"),
    ("motor vehicle", "Consumer Cyclical", "Auto Manufacturers"),
    ("motor home", "Consumer Cyclical", "Auto Manufacturers"),
    ("retail-department", "Consumer Cyclical", "Department Stores"),
    ("retail-family clothing", "Consumer Cyclical", "Apparel Retail"),
    ("retail-womens clothing", "Consumer Cyclical", "Apparel Retail"),
    ("retail-shoe", "Consumer Cyclical", "Apparel Retail"),
    ("retail-catalog", "Consumer Cyclical", "Internet Retail"),
    ("retail-grocery", "Consumer Defensive", "Grocery Stores"),
    ("retail-convenience", "Consumer Defensive", "Grocery Stores"),
    ("retail-variety", "Consumer Defensive", "Discount Stores"),
    ("retail-eating place", "Consumer Cyclical", "Restaurants"),
    ("retail-drinking place", "Consumer Cyclical", "Restaurants"),
    ("hotels & motels", "Consumer Cyclical", "Lodging"),
    ("amusement", "Consumer Cyclical", "Leisure"),
    ("food & kindred", "Consumer Defensive", "Packaged Foods"),
    ("candy & other confection", "Consumer Defensive", "Confectioners"),
    ("bottled & canned soft drink", "Consumer Defensive", "Beverages - Non-Alcoholic"),
    ("malt beverage", "Consumer Defensive", "Beverages - Brewers"),
    ("wines, brandy", "Consumer Defensive", "Beverages - Wineries & Distilleries"),
    ("distilled & blended", "Consumer Defensive", "Beverages - Wineries & Distilleries"),
    ("cigarettes", "Consumer Defensive", "Tobacco"),
    ("soap & other detergent", "Consumer Defensive", "Household & Personal Products"),
    ("perfumes, cosmetics", "Consumer Defensive", "Household & Personal Products"),
    ("agricultural production", "Consumer Defensive", "Farm Products"),
    ("telephone communications", "Communication Services", "Telecom Services"),
    ("radiotelephone", "Communication Services", "Telecom Services"),
    ("television broadcasting", "Communication Services", "Broadcasting"),
    ("radio broadcasting", "Communication Services", "Broadcasting"),
    ("cable & other pay television", "Communication Services", "Entertainment"),
    ("newspapers", "Communication Services", "Publishing"),
    ("periodicals", "Communication Services", "Publishing"),
    ("books: publishing", "Communication Services", "Publishing"),
    ("motion picture", "Communication Services", "Entertainment"),
    ("advertising", "Communication Services", "Advertising Agencies"),
    ("membership sports", "Communication Services", "Gambling"),
    ("holding compan", "Industrials", "Conglomerates"),
)


def _normalize_sic(sic: Optional[Union[str, int]]) -> Optional[str]:
    """Return a 4-digit zero-padded SIC string, or ``None`` when unusable."""
    if sic is None:
        return None
    s = str(sic).strip()
    if not s or not s.isdigit():
        return None
    return s.zfill(4)


def map_sic_to_yahoo(
    sic: Optional[Union[str, int]], sic_description: Optional[str] = None
) -> Optional[Tuple[str, str]]:
    """Map an SEC SIC code (+ description) to ``(yahoo_sector, yahoo_industry)``.

    Resolution: exact 4-digit → 2-digit major group → description keyword.
    Returns ``None`` when nothing matches (caller keeps its own fallback).
    """
    code = _normalize_sic(sic)
    if code is not None:
        hit = SIC_TO_YAHOO.get(code)
        if hit is not None:
            return hit
        hit2 = SIC2_TO_YAHOO.get(code[:2])
        if hit2 is not None:
            return hit2

    desc = (sic_description or "").lower().strip()
    if desc:
        for kw, sect, ind in SIC_DESC_KEYWORDS:
            if kw in desc:
                return (sect, ind)
    return None


__all__ = [
    "SIC_TO_YAHOO",
    "SIC2_TO_YAHOO",
    "SIC_DESC_KEYWORDS",
    "map_sic_to_yahoo",
]
