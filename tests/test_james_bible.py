from pyboy import PyBoy

def test_bible():
    pyboy = PyBoy("./roms/bible.gb", window="SDL2")
    try:
        pyboy.button_press("START")
        pyboy.tick(900, True) 
        pyboy.button_press("START")
        pyboy.tick(60, True)  
        pyboy.button_press("START")
        pyboy.tick(60, True) 

        
        assert pyboy.tilemap_background[7:17, 0] == [
            328, 367, 364, 377, 288, 322, 361, 354,364, 357
        ], "Expected 'Holy Bible' title screen"
    finally:
        pyboy.stop()

def test_wisdom_tree():
    pyboy = PyBoy("./roms/bible.gb", window="null")
    cart = pyboy.mb.cartridge

    expected_low = cart.rombanks[4, 0x0150]
    expected_high = cart.rombanks[5, 0]

    pyboy.mb.setitem(0x0002, 0x99)

    assert cart.rombank_selected_low == 4
    assert cart.rombank_selected == 5
    assert pyboy.mb.getitem(0x0150) == expected_low
    assert pyboy.mb.getitem(0x4000) == expected_high

    print("PASS: bible.gb Wisdom Tree switching works")
    pyboy.stop()

def test_multibank():
    pyboy = PyBoy("./roms/bible.gb", window="null")
    cart = pyboy.mb.cartridge

    expected_high = cart.rombanks[5, 0]
    pyboy.mb.setitem(0x2000, 5)

    assert cart.rombank_selected == 5
    assert pyboy.mb.getitem(0x4000) == expected_high

    print("PASS: bible.gb ROMOnly multibank switching works")
    pyboy.stop()

