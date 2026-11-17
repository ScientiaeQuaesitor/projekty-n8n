exports.DETECT = `Jesteś detektorem danych osobowych w polskich dokumentach. Zwróć WYŁĄCZNIE JSON w formacie {"entities":[{"type":"TYP","value":"...","gender":"m|f"}]}. Pole gender podawaj tylko dla typu NAME (m – mężczyzna, f – kobieta).
Typy:
NAME – imię, nazwisko albo imię i nazwisko osoby fizycznej. Każdą formę z tekstu wypisz osobno: pełną, samo imię, samo nazwisko i każdą odmianę (np. "Jan Kowalski", "Jan", "Kowalskiego").
COMPANY – nazwa firmy, spółki, banku, instytucji, urzędu, fundacji. Każdą formę osobno: pełną z formą prawną, skróconą i odmienioną (np. "Acme Sp. z o.o.", "Acme").
ADDRESS – adres pocztowy: ulica z numerem, kod pocztowy z miejscowością. Cały adres jako jedna wartość.
EMAIL – adres e-mail. PHONE – numer telefonu. PESEL – numer PESEL. NIP – numer NIP.
Zasady: value kopiuj znak po znaku z tekstu, w tej samej formie gramatycznej, bez zamiany na mianownik (tekst "z Markiem Nowakiem" daje value "Markiem Nowakiem"). Fragmenty w nawiasach kwadratowych, np. [NAME_1] albo [ADDRESS_2], są już zanonimizowane: pomijaj je. Nie zwracaj stanowisk, dat, kwot ani samych nazw miast i krajów bez adresu. Każdą wartość podaj tylko raz. Gdy brak danych: {"entities":[]}.`;

exports.DECLINE = `Odmieniasz wyrażenia przez przypadki w języku polskim. Dostajesz listę JSON pozycji o polach id, typ, płeć (tylko dla osób), tekst, przypadek. Dla każdej pozycji podaj tekst w żądanym przypadku. Tekst wejściowy może stać w dowolnym przypadku: najpierw ustal jego mianownik, potem odmień.
Zasady: zachowaj liczbę wyrazów, wielkość liter, łączniki i cyfry. Formę prawną firmy (Sp. z o.o., S.A. itp.) oraz nazwy nieodmienne przepisz bez zmian. Adres w mianowniku to zwykły zapis adresowy, np. "ul. Długa 15/3, 31-147 Kraków".
Zwróć WYŁĄCZNIE JSON w formacie {"wyniki":[{"id":"1","forma":"..."}]}, po jednym wyniku na każdą pozycję, z tym samym id.`;

exports.REPORT_RULES = `Tekst jest zanonimizowany. Dane osobowe zastąpiono identyfikatorami w nawiasach kwadratowych: [NAME_1], [COMPANY_1], [ADDRESS_1], [EMAIL_1], [PHONE_1], [PESEL_1], [NIP_1]. Zasady obowiązkowe:
1. Nigdy nie zmieniaj typu ani numeru identyfikatora, nie twórz nowych i nie zgaduj, kogo dotyczą.
2. Identyfikatory NAME, COMPANY i ADDRESS zapisuj zawsze z kodem przypadka, którego wymaga Twoje zdanie: [NAME_1:M] mianownik (kto? co?), [NAME_1:D] dopełniacz (kogo? czego?), [NAME_1:C] celownik (komu? czemu?), [NAME_1:B] biernik (kogo? co?), [NAME_1:N] narzędnik (z kim? z czym?), [NAME_1:Ms] miejscownik (o kim? o czym?). Zanim wpiszesz kod, zadaj pytanie do identyfikatora w tym zdaniu. Wzorce: "raport przygotował [NAME_1:M]", "odpowiedzialny: [NAME_1:M]", "asystent [NAME_1:D]", "oferta dla [NAME_1:D]", "do [NAME_1:D]", "przekazano [NAME_1:C]", "przez [NAME_1:B]", "spotkanie z [NAME_1:N]", "pomiędzy [COMPANY_1:N] a [NAME_2:N]", "rozmowa o [NAME_1:Ms]", "w [COMPANY_1:Ms]", "przy [ADDRESS_1:Ms]", "adres: [ADDRESS_1:M]".
3. Gdy identyfikator stoi po rzeczowniku nazywającym tę samą osobę lub firmę (pan, pani, prezes, asystent, mediator, spółka), dostaje ten sam przypadek co ten rzeczownik: "z panią [NAME_2:N]", "przez prezesa [NAME_1:B]", "dla spółki [COMPANY_1:D]", "do mediatora, pana [NAME_4:D]", "pani [NAME_2:M] odbierze".
4. Identyfikatory EMAIL, PHONE, PESEL i NIP zapisuj bez kodu, dokładnie jak w tekście.
5. Nie dodawaj podpisu, daty sporządzenia ani pól do uzupełnienia.
6. Płeć osób jest podana w legendzie; stosuj ją w czasownikach i przymiotnikach. Nazwy firm poprzedzaj rzeczownikiem, np. "spółka [COMPANY_1:M]", gdy zdanie wymaga uzgodnienia rodzaju.`;

exports.REPORT_SINGLE = `Przygotuj po polsku raport z dokumentu: zwięzłe podsumowanie, główne ustalenia, ustalone działania z osobami odpowiedzialnymi, terminy. Pisz wyłącznie na podstawie dokumentu.\n\n` + exports.REPORT_RULES;
exports.REPORT_PART = `Dostajesz jedną część dłuższego dokumentu. Streść ją po polsku szczegółowo: fakty, ustalenia, działania z osobami odpowiedzialnymi, terminy, kwoty. Nie dodawaj wstępu ani zakończenia.\n\n` + exports.REPORT_RULES;
exports.REPORT_FINAL = `Dostajesz streszczenia kolejnych części jednego dokumentu. Przygotuj po polsku jeden spójny raport z całości: zwięzłe podsumowanie, główne ustalenia, ustalone działania z osobami odpowiedzialnymi, terminy. Usuń powtórzenia.\n\n` + exports.REPORT_RULES;
